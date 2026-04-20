import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, cast
import uuid

from pydantic import BaseModel, Field
from sympy import content

# EventBus 核心组件
from core.event_bus.event_bus import (
    Event, EventBus, EventRegistry, EventHandlerRegistry,
    EventHandler, EventDeclaration, TaskErrorPayload, ShutdownEvent
)
from core.event_bus.templates.expect import expect
from core.event_bus.templates.request import RequestProtocol, ResponseProtocol, request
from core.event_bus.templates.pipe import open_pipe, PipeClosedError

# LLM 客户端
from components.llm.messages_model import *
from components.llm.llm_clients import (
    Messages, StreamChunk, UsageStats, OpenAIClient
)
from components.llm.handlers import (
    LLMService, LLMRequest, LLMAccepted,
    LLMPipeConnectEvent, LLMPipeLinkedEvent, llmservice_events
)

# 对话管理器
from components.context.conversation import ConversationManager

# 简单 TUI
from components.simple_tui.ui import *

# 配置日志
log_file = Path("./logs/log.txt")
log_file.parent.mkdir(parents=True, exist_ok=True)
handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding='utf-8')]
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=handlers,
    force=True,
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 核心业务逻辑处理器
# ----------------------------------------------------------------------

class CoreLogicHandler(EventHandler):
    """
    监听来自 UI 的事件，协调对话管理、LLM 调用，并将结果通过 UI 事件发回。
    处理完成后必须发布 UIInputResponseEvent 作为同步响应。
    """

    def __init__(self, conv_manager: ConversationManager) -> None:
        super().__init__([
            UIInputEvent.name,
            UICommandEvent.name,
            ShutdownEvent.name,
        ], handle_timeout=180)
        self.conv_manager = conv_manager
        # 保存当前流式输出的助手回复内容（用于最终保存）
        self._assistant_content_parts: List[str] = []

    async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
        if raw_event.name == ShutdownEvent.name:
            return

        if raw_event.name == UIInputEvent.name:
            assert isinstance(payload, UIInputPayload)
            await self._handle_input(payload, bus_proxy)
        elif raw_event.name == UICommandEvent.name:
            assert isinstance(payload, UICommandPayload)
            await self._handle_command(payload, bus_proxy)

    async def _handle_input(self, payload: UIInputPayload, bus_proxy: EventBus.Proxy) -> None:
        # 提取请求标识信息，用于最终响应
        session_id = payload.session_id
        request_id = payload.request_id
        user_message = payload.message

        # 1. 保存用户消息到对话树
        _ = await self.conv_manager.add_message(
            role="user",
            content=user_message,
            branchable=False
        )

        # 2. 获取历史并构建 Messages
        try:
            history: List[Dict[str, Any]] = await self.conv_manager.get_linear_history()
        except Exception as e:
            logger.error(f"Failed to load conversation history: {e}")
            history = []

        messages: Messages = build_messages(history)
        messages.append(build_message({'role':'user', 'content': user_message}))

        # 3. 向 LLMService 发起请求，等待接受响应
        try:
            accepted: ResponseProtocol = await request(
                bus_proxy=bus_proxy,
                req_event="llm.request",
                req_data={"llm_messages": messages},
                resp_event="llm.accepted",
                timeout=10.0,
                session_id=session_id,   # 复用 UI 请求的会话 ID
            )
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            # 发布错误信息到 UI，并立即返回失败响应
            await bus_proxy.publish(
                UIOutputTextEvent.name,
                UIOutputTextPayload(text=f"⚠️ LLM request failed: {e}").model_dump()
            )
            await self._send_response(bus_proxy, session_id, request_id, False, f"LLM request failed: {e}")
            return

        if not accepted.success:
            await bus_proxy.publish(
                UIOutputTextEvent.name,
                UIOutputTextPayload(text=f"⚠️ LLM service rejected: {accepted.error_msg}").model_dump()
            )
            await self._send_response(bus_proxy, session_id, request_id, False, accepted.error_msg)
            return

        # 4. 建立管道连接，流式接收回复
        self._assistant_content_parts.clear()
        try:
            async with open_pipe(
                bus_proxy=bus_proxy,
                req_event=LLMPipeConnectEvent.name,
                resp_event=LLMPipeLinkedEvent.name,
                session_id=session_id,
                handshake_timeout=5.0,
            ) as pipe:
                while True:
                    try:
                        chunk: StreamChunk = cast(StreamChunk, await pipe.receive())
                    except PipeClosedError:
                        break

                    # 将流式块转发给 UI
                    await bus_proxy.publish(
                        UIOutputStreamEvent.name,
                        UIOutputStreamChunk(chunk=chunk)
                    )

                    if chunk.type == StreamChunk.ChunkType.TEXT and chunk.text:
                        self._assistant_content_parts.append(chunk.text)
                    elif chunk.type == StreamChunk.ChunkType.DONE:
                        break

        except Exception as e:
            logger.error(f"Pipe communication error: {e}", exc_info=True)
            await bus_proxy.publish(
                UIOutputTextEvent.name,
                UIOutputTextPayload(text=f"\n⚠️ Pipe error: {e}").model_dump()
            )
            await self._send_response(bus_proxy, session_id, request_id, False, f"Pipe error: {e}")
            return

        # 5. 流式完成，保存助手回复并通知 UI
        await bus_proxy.publish(UIOutputDoneEvent.name, None)

        assistant_content = "".join(self._assistant_content_parts)
        if assistant_content:
            await self.conv_manager.add_message(
                role="assistant",
                content=assistant_content,
                branchable=True
            )

        # 发送成功响应
        await self._send_response(bus_proxy, session_id, request_id, True, None)

    async def _handle_command(self, payload: UICommandPayload, bus_proxy: EventBus.Proxy) -> None:

        session_id = payload.session_id
        request_id = payload.request_id
        command = payload.command
        args = payload.args
        output_text = ""
        success = True

        try:
            if command == "/fork":
                branch_point = args[0]
                await self.conv_manager.fork(branch_point)
                output_text = f"🔀 Forked new branch at node: {branch_point}"
                logger.info(f"Forked conversation at {branch_point}")

            elif command == "/switch":
                if not args:
                    output_text = "⚠️ Usage: /switch <node_id> <branch_node_id>"
                    success = False
                else:
                    await self.conv_manager.switch_to_branch(
                        node_id=args[0],
                        target_branch_id=args[1]
                    )
                    output_text = f"🔀 Switched to branch: {args[0]}"
                    logger.info(f"Switched to branch {args[1]}")

            elif command == "/clear":
                await self.conv_manager.clear()
                output_text = "🧹 Conversation cleared."
                logger.info("Conversation cleared")

            elif command == "/history":
                nodes = await self.conv_manager.get_linear_nodes()
                lines = ["\n📜 Current conversation path:"]
                for i, node in enumerate(nodes, 1):
                    marker = "🌿" if node["branchable"] else "•"
                    preview = node["content"][:60] + ('...' if len(node["content"]) > 60 else '')
                    lines.append(f"  {i}. [{node['role']}, {node['id']}] {marker} {preview}")
                    children_ids = await self.conv_manager.get_children_ids(node['id'])
                    if len(children_ids) > 1:
                        lines.append(f"   - {children_ids}")
                output_text = "\n".join(lines)

            else:
                output_text = f"❓ Unknown command: {command}. Try: /fork <node_id>, /switch <node_id> <branch_id>, /clear, /history"
                success = False

        except Exception as e:
            output_text = f"⚠️ Command failed: {e}"
            logger.error(f"Command {command} failed: {e}", exc_info=True)
            success = False

        # 将命令执行结果发送给 UI（实时输出）
        if output_text:
            await bus_proxy.publish(
                UIOutputTextEvent.name,
                UIOutputTextPayload(text=output_text).model_dump()
            )

        # 发送同步响应，让 UI 的 request 调用返回
        await self._send_response(bus_proxy, session_id, request_id, success, None if success else output_text)

    async def _send_response(
        self,
        bus_proxy: EventBus.Proxy,
        session_id: str,
        request_id: str,
        success: bool,
        error_msg: Optional[str]
    ) -> None:
        """发布 UIInputResponseEvent 作为对 UI 请求的最终响应"""
        response = UIInputResponsePayload(
            session_id=session_id,
            request_id=request_id,
            success=success,
            error_msg=error_msg
        )
        await bus_proxy.publish(UIInputResponseEvent.name, response)

# ----------------------------------------------------------------------
# 主函数
# ----------------------------------------------------------------------

async def main() -> None:
    # 初始化事件注册表与处理器注册表
    event_registry = EventRegistry()
    handler_registry = EventHandlerRegistry()

    # 初始化对话管理器
    conv_manager = ConversationManager(db_path="./data/conversations.db")

    # 初始化 LLM 客户端
    llm_client = OpenAIClient(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
        model="deepseek-chat"
    )

    # 注册 LLMService 所需的事件
    llmservice_events.register_all_events(event_registry)
    # 创建并注册 LLMService 处理器
    llm_service = LLMService(llm_client=llm_client, max_semaphore=8)
    handler_registry.register(llm_service)

    # 注册简易 TUI 所需的事件
    simple_tui_events.register_all_events(event_registry) 
    # 注册简易 TUI
    simple_tui_handlers.register_all_handlers(handler_registry)

    # 创建核心业务逻辑处理器（负责协调 UI 事件与对话/LLM）
    core_handler = CoreLogicHandler(conv_manager)
    handler_registry.register(core_handler)

    # 日志处理器（可选）
    class LogHandler(EventHandler):
        def __init__(self) -> None:
            super().__init__([".*"])
        async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
            if raw_event.name not in ("ui.output.stream",):  # 避免日志洪水
                logger.info(f"Event: {raw_event.name} | sources: {raw_event.sources} | id: {raw_event.id}")
    handler_registry.register(LogHandler())

    # 任务错误报告器
    class TaskErrorReporter(EventHandler):
        def __init__(self) -> None:
            super().__init__(["event_bus.__task_error__"])
        async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
            if isinstance(payload, TaskErrorPayload):
                print(f"ERROR_IN_HANDLER: {payload.handler_name} | {payload.error_type} | {payload.error_message}")
    handler_registry.register(TaskErrorReporter())

    # 启动事件总线
    async with EventBus(event_registry, handler_registry) as bus:
        logger.info("EventBus + ConversationManager running.")
        main_puber = bus.proxy('main')
        # 创建 UI 并运行
        async with conv_manager:
            try:
                async with expect(main_puber,'ui.exit') as exit_event:
                    await main_puber.publish('ui.start')
                    try:
                        await exit_event
                    except asyncio.CancelledError:
                        pass
            finally:
                await llm_service.shutdown()

        logger.info("Resources cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())