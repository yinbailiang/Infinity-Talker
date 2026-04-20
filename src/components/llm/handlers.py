import asyncio
from typing import Any, List, Set

from pydantic import BaseModel, Field

from core.event_bus.event_bus import Event, EventBus, EventDeclaration, EventHandler, EventRegistry, ShutdownEvent
from core.event_bus.templates.pipe import Pipe, PipeClosedError, expect_pipe, PipeOpenRequest, PipeLinkedResponse
from core.event_bus.templates.register import ModuleEventRegister
from core.event_bus.templates.request import RequestProtocol, ResponseProtocol

from components.llm.llm_clients import LLMClient

from .messages_model import Messages

llmservice_events = ModuleEventRegister(__name__)

# ---------- 事件与数据模型定义 ----------
class LLMRequest(RequestProtocol):
    """LLM 请求负载，携带对话消息"""
    llm_messages: Messages = Field(description="llm对话消息")
@llmservice_events.event
class LLMRequestEvent(EventDeclaration):
    name = 'llm.request'
    payload_type = LLMRequest


class LLMAccepted(ResponseProtocol):
    pass
@llmservice_events.event
class LLMAcceptedEvent(EventDeclaration):
    name = 'llm.accepted'
    payload_type = LLMAccepted

@llmservice_events.event
class LLMPipeConnectEvent(EventDeclaration):
    name = 'llm.pipe.connect'
    payload_type = PipeOpenRequest
@llmservice_events.event
class LLMPipeLinkedEvent(EventDeclaration):
    name = 'llm.pipe.linked'
    payload_type = PipeLinkedResponse


# ---------- LLMService 处理器 ----------
class LLMService(EventHandler):
    """LLM 服务处理器"""

    def __init__(self,llm_client: LLMClient, max_semaphore: int = 8,subscriptions: List[str] = ['llm.request', ShutdownEvent.name],handle_timeout: float = 15.0) -> None:
        super().__init__(subscriptions, handle_timeout)
        self.llm: LLMClient = llm_client
        
        self.llm_tasks: Set[asyncio.Task[Any]] = set()
        self.tasks_max_semaphore: asyncio.Semaphore = asyncio.Semaphore(max_semaphore)

    async def handle(self, payload: BaseModel | None, bus_proxy: EventBus.Proxy, raw_event: Event) -> None:
        if raw_event.name == ShutdownEvent.name:
            await self.shutdown()
            return

        if not isinstance(payload, LLMRequest):
            return
        
        # 1. 创建子任务，等待管道连接并推送流式数据
        task: asyncio.Task[None] = asyncio.create_task(
            self._stream_via_pipe( payload.session_id,payload.llm_messages, bus_proxy)
        )
        self.llm_tasks.add(task)
        task.add_done_callback(self._on_task_done)

        # 2. 返回接受响应，告知客户端管道
        await bus_proxy.publish(
            name="llm.accepted",
            data=LLMAccepted(
                session_id=payload.session_id,
                request_id=payload.request_id,
                success=True,
            )
        )

    async def _stream_via_pipe(
        self,
        session_id: str,
        messages: Messages,
        bus_proxy: EventBus.Proxy,
    ) -> None:
        """
        子任务：等待管道连接，流式生成并通过管道发送。
        """
        # 等待客户端发起管道连接（expect_pipe 会阻塞直到收到 PipeOpenRequest）
        async with expect_pipe(
            bus_proxy=bus_proxy,
            req_event=LLMPipeConnectEvent.name,
            resp_event=LLMPipeLinkedEvent.name,
            session_id=session_id,
            timeout=30.0,  # 握手超时
        ) as pipe:
            # 管道连接成功，开始 LLM 流式生成并推送
            await self._generate_and_stream(pipe, messages)

    async def _generate_and_stream(
        self,
        pipe: Pipe,
        messages: Messages,
    ) -> None:
        """执行 LLM 调用并通过管道发送流式块"""
        async with self.tasks_max_semaphore:
            async with self.llm:
                async for chunk in self.llm.stream_chat(messages=messages):
                    try:
                        await pipe.send(chunk)
                    except PipeClosedError:
                        break

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self.llm_tasks.discard(task)

    async def shutdown(self) -> None:
        """优雅关闭：取消所有未完成的子任务"""
        if self.llm_tasks:
            tasks = list(self.llm_tasks)
            self.llm_tasks.clear()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*self.llm_tasks, return_exceptions=True)
