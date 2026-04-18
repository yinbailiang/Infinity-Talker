import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# EventBus 核心组件
from core.event_bus.event_bus import BusShuttingDown, Event, EventBus, EventDeclaration, EventHandler, EventRegistry, EventHandlerRegistry, TaskErrorPayload
from core.event_bus.templates.request import request, RequestProtocol, ResponseProtocol

# LLM 客户端
from componets.llm.llm_clients import ContentType, LLMClient, Message, MessageRole, Messages, MultiModalContent, StreamChunk, UsageStats, OpenAIClient

# 🆕 引入对话管理器
from componets.context.conversation import ConversationManager

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


async def main():
    # 初始化注册表
    event_registry = EventRegistry()
    handler_registry = EventHandlerRegistry()
    
    # 定义事件类型
    class InputPayload(RequestProtocol):
        message: str = Field(description="输入消息内容")
        # 🆕 扩展：支持命令前缀与会话标识
        command: Optional[str] = Field(default=None, description="特殊命令: /fork, /switch, /clear, /history")
        target_node_id: Optional[str] = Field(default=None, description="命令目标节点ID（用于/switch）")

    class InputEvent(EventDeclaration):
        name = "input"
        payload_type = InputPayload

    class LLMGenerationDoneEvent(EventDeclaration):
        name = "llm.generation.done"
        payload_type = ResponseProtocol

    event_registry.register(InputEvent)
    event_registry.register(LLMGenerationDoneEvent)

    # 🆕 初始化对话管理器（与 EventBus 生命周期绑定）
    conv_manager = ConversationManager(db_path="./data/conversations.db")
    await conv_manager.connect()  # 手动初始化，因未使用 async with

    class InputEventHandler(EventHandler):
        def __init__(self, conv_manager: ConversationManager) -> None:
            super().__init__(["input"], handle_timeout=60.0)
            self.conv_manager = conv_manager
            self.llm = OpenAIClient(
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url="https://api.deepseek.com",
                model="deepseek-chat"
            )

        async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
            if not isinstance(payload, InputPayload):
                logger.error(f"Invalid payload type: expected InputPayload, got {type(payload)}")
                return

            session_id = getattr(payload, "session_id", "default")
            
            # 🆕 1. 处理特殊命令（不经过 LLM）
            if payload.command:
                await self._handle_command(payload.command, payload.target_node_id,payload.request_id, session_id, bus_proxy)
                return

            # 🆕 2. 获取当前会话的线性历史（自动过滤虚拟根节点）
            try:
                history: List[Dict[str, Any]] = await self.conv_manager.get_linear_history()
            except Exception as e:
                logger.error(f"Failed to load conversation history: {e}")
                history = []

            # 🆕 3. 保存用户输入到对话树（branchable=False：普通消息不创建分支点）
            _ = await self.conv_manager.add_message(
                role="user",
                content=payload.message,
                branchable=False
            )
            print(f"\n[You] {payload.message}")

            # 🆕 4. 构建 LLM 请求消息（历史 + 当前输入）
            messages: Messages = [
                Message(
                    role=MessageRole(msg["role"]),
                    content=[MultiModalContent(type=ContentType.TEXT, text=msg["content"])]
                )
                for msg in history
            ]
            messages.append(
                Message(
                    role=MessageRole.USER,
                    content=[MultiModalContent(type=ContentType.TEXT, text=payload.message)]
                )
            )

            # 🆕 5. 流式调用 LLM 并实时输出
            assistant_content_parts: List[str] = []
            async with self.llm:
                try:
                    async for chunk in self.llm.stream_chat(messages=messages):
                        if chunk.type == StreamChunk.ChunkType.TEXT:
                            if chunk.text is None:
                                continue
                            print(chunk.text, end='', flush=True)
                            assistant_content_parts.append(chunk.text)
                        elif chunk.type == StreamChunk.ChunkType.USAGE:
                            assert chunk.usage is not None
                            print(f"\n[Usage] Prompt: {chunk.usage.prompt_tokens}, Completion: {chunk.usage.completion_tokens}, Total: {chunk.usage.total_tokens}")
                            logger.info(f"Usage: {chunk.usage}")
                        elif chunk.type == StreamChunk.ChunkType.DONE:
                            print()  # 换行
                            logger.info("Stream completed.")
                finally:
                    # 🆕 6. 保存 LLM 回复到对话树（branchable=True：标记为可分支点，便于后续 /fork）
                    assistant_content = "".join(assistant_content_parts)
                    if assistant_content:
                        await self.conv_manager.add_message(
                            role="assistant",
                            content=assistant_content,
                            branchable=True  # ✅ 关键：助理回复作为潜在分支点
                        )
                    
                    # 🆕 7. 发布完成事件（携带最新节点信息，供其他组件响应）
                    current_node = await self.conv_manager.get_current_node_id()
                    await bus_proxy.publish(
                        name="llm.generation.done",
                        data={
                            "session_id": session_id,
                            "request_id": getattr(payload, "request_id", ""),
                            "current_node_id": current_node,
                            "response": assistant_content,
                        },
                    )

        async def _handle_command(
            self,
            command: str,
            target_node_id: Optional[str],
            request_id: str,
            session_id: str,
            bus_proxy: EventBus.Proxy
        ) -> None:
            """处理特殊命令：/fork, /switch, /clear, /history"""
            try:
                if command == "/fork":
                    # 在最近的可分支点创建新分支
                    branch_point = await self.conv_manager.get_last_branchable_node_id()
                    await self.conv_manager.fork(branch_point)
                    print(f"🔀 Forked new branch at node: {branch_point}")
                    logger.info(f"Forked conversation at {branch_point}")
                    
                elif command == "/switch" and target_node_id:
                    # 切换到指定节点的分支
                    await self.conv_manager.switch_to_branch(
                        node_id=target_node_id,
                        target_branch_id=target_node_id  # 简化：假设目标节点即为分支头
                    )
                    print(f"🔀 Switched to branch: {target_node_id}")
                    logger.info(f"Switched to branch {target_node_id}")
                    
                elif command == "/clear":
                    await self.conv_manager.clear()
                    print("🧹 Conversation cleared.")
                    logger.info("Conversation cleared")
                    
                elif command == "/history":
                    nodes = await self.conv_manager.get_linear_nodes()
                    print("\n📜 Current conversation path:")
                    for i, node in enumerate(nodes, 1):
                        marker = "🌿" if node["branchable"] else "•"
                        print(f"  {i}. [{node['role']}] {marker} {node['content'][:60]}{'...' if len(node['content']) > 60 else ''}")
                        
                else:
                    print(f"❓ Unknown command: {command}. Try: /fork, /switch <node_id>, /clear, /history")
                    
            except Exception as e:
                print(f"⚠️ Command failed: {e}")
                logger.error(f"Command {command} failed: {e}", exc_info=True)
            
            # 发布命令执行完成事件
            await bus_proxy.publish(
                name="llm.generation.done",
                data={"request_id": request_id, "session_id": session_id, "command_handled": command},
            )

    # 🆕 注入 conv_manager 依赖
    handler_registry.register(InputEventHandler(conv_manager))

    class LogHandler(EventHandler):
        def __init__(self) -> None:
            super().__init__([".*"])
        
        async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
            logger.info(f"Event: {raw_event.name} | sources: {raw_event.sources} | id: {raw_event.id}")

    handler_registry.register(LogHandler())

    class TaskErrorReporter(EventHandler):
        def __init__(self) -> None:
            super().__init__(["event_bus.__task_error__"])

        async def handle(self, payload: Optional[BaseModel], bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
            if isinstance(payload, TaskErrorPayload):
                print(f"ERROR_IN_HANDLER: {payload.handler_name} | {payload.error_type} | {payload.error_message}")

    handler_registry.register(TaskErrorReporter())

    async def read_input_and_publish(bus: EventBus) -> None:
        """从控制台读取输入并发布事件（支持命令解析）"""
        proxy = bus.proxy("main")
        print("💡 Commands: /fork, /switch <node_id>, /clear, /history, exit")
        
        while True:
            try:
                user_input = await asyncio.to_thread(input, "\n> ")
                if user_input.lower() == "exit":
                    logger.info("Exiting...")
                    break
                
                # 🆕 解析命令前缀
                command: Optional[str] = None
                target_node_id: Optional[str] = None
                message_content = user_input
                
                if user_input.startswith("/"):
                    parts = user_input.strip().split(maxsplit=1)
                    command = parts[0]
                    if command == "/switch" and len(parts) > 1:
                        target_node_id = parts[1]
                        message_content = ""  # switch 不需要消息内容
                    elif command in ["/fork", "/clear", "/history"]:
                        message_content = ""
                
                await request(
                    bus_proxy=proxy,
                    req_event="input",
                    req_data={
                        "message": message_content,
                        "command": command,
                        "target_node_id": target_node_id,
                    },
                    session_id="default",
                    resp_event="llm.generation.done",
                    timeout=60.0  # 延长超时，适应流式生成
                )
            except KeyboardInterrupt:
                print("\n⚠️ Interrupted. Type 'exit' to quit cleanly.")
            except Exception as e:
                logger.error(f"Input error: {e}", exc_info=True)
                print(f"⚠️ Error: {e}")

    # 🆕 启动 EventBus + 对话管理器（生命周期对齐）
    try:
        async with EventBus(event_registry, handler_registry) as bus:
            logger.info("EventBus + ConversationManager running.")
            await read_input_and_publish(bus)
                
    finally:
        # 🆕 确保对话管理器资源释放
        await conv_manager.close()
        logger.info("Resources cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())