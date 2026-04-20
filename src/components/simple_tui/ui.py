from ast import List
import asyncio
from typing import List, Optional

from pydantic import BaseModel, Field

from components.llm.llm_clients import StreamChunk
from core.event_bus.event_bus import Event, EventBus, EventDeclaration, EventHandler
from core.event_bus.templates.register import ModuleEventRegister, ModuleHandlerRegister
from core.event_bus.templates.request import (
    RequestProtocol,
    ResponseProtocol,
    request,
)

simple_tui_events = ModuleEventRegister(__name__)
simple_tui_handlers = ModuleHandlerRegister(__name__)

# ------------------------------------------------------------------
# UI生命周期事件（system → UI）
# ------------------------------------------------------------------
@simple_tui_events.event
class UIStartEvent(EventDeclaration):
    name = 'ui.start'
@simple_tui_events.event
class UIExitEvent(EventDeclaration):
    name = 'ui.exit'

# ------------------------------------------------------------------
# 请求事件（UI → Core）—— 继承 RequestProtocol
# ------------------------------------------------------------------
class UIInputPayload(RequestProtocol):
    """普通消息输入"""
    message: str = Field(description="用户输入的原始文本")

@simple_tui_events.event
class UIInputEvent(EventDeclaration):
    name = "ui.input.submit"
    payload_type = UIInputPayload


class UICommandPayload(RequestProtocol):
    """命令输入"""
    command: str = Field(description="命令名，如 /fork")
    args: List[str] = Field(description="命令参数")

@simple_tui_events.event
class UICommandEvent(EventDeclaration):
    name = "ui.command.exec"
    payload_type = UICommandPayload

# ------------------------------------------------------------------
# 响应事件（Core → UI）—— 继承 ResponseProtocol，用于 request 等待
# ------------------------------------------------------------------
class UIInputResponsePayload(ResponseProtocol):
    """普通消息/命令处理的最终响应"""
    pass

@simple_tui_events.event
class UIInputResponseEvent(EventDeclaration):
    name = "ui.input.response"
    payload_type = UIInputResponsePayload


# ------------------------------------------------------------------
# 流式输出事件（Core → UI）—— 保持独立，不参与 request 配对
# ------------------------------------------------------------------
class UIOutputTextPayload(BaseModel):
    text: str = Field(description="普通文本输出")
    end: str = Field(default="\n")

@simple_tui_events.event
class UIOutputTextEvent(EventDeclaration):
    name = "ui.output.text"
    payload_type = UIOutputTextPayload


class UIOutputStreamChunk(BaseModel):
    chunk: StreamChunk  # 直接透传 StreamChunk

@simple_tui_events.event
class UIOutputStreamEvent(EventDeclaration):
    name = "ui.output.stream"
    payload_type = UIOutputStreamChunk

@simple_tui_events.event
class UIOutputDoneEvent(EventDeclaration):
    name = "ui.output.done"
    payload_type = None  # 仅作信号


# ------------------------------------------------------------------
# 控制台 UI 实现
# ------------------------------------------------------------------
class ConsoleUI:
    """控制台交互界面，通过 request 机制等待每次请求的最终响应"""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._running = False

    async def run(self):
        """启动输入循环"""
        self._running = True
        proxy = self.bus.proxy("ConsoleUI")
        try:
            print("💡 Commands: /fork <node_id>, /switch <node_id> <branch_node_id>, /clear, /history, /exit")

            while self._running:
                user_input = await asyncio.to_thread(input, "\n> ")

                if user_input.lower() == "/exit":
                    self._running = False
                    break

                # 使用 request 发起调用，等待最终响应
                if user_input.startswith("/"):
                    parts = user_input.strip().split()
                    command = parts[0]
                    args = parts[1:]
                    resp = await request(
                        bus_proxy=proxy,
                        req_event="ui.command.exec",
                        req_data={"command": command, "args": args},
                        resp_event="ui.input.response",
                    )
                else:
                    resp = await request(
                        bus_proxy=proxy,
                        req_event="ui.input.submit",
                        req_data={"message": user_input},
                        resp_event="ui.input.response",
                    )

                # 检查业务处理是否成功（可选）
                resp.raise_if_failed()

        finally:
            await proxy.publish('ui.exit')

    def print_text(self, text: str, end: str = "\n"):
        print(text, end=end, flush=True)

    def print_stream_chunk(self, chunk: StreamChunk):
        if chunk.type == StreamChunk.ChunkType.TEXT:
            if chunk.text:
                print(chunk.text, end='', flush=True)
        elif chunk.type == StreamChunk.ChunkType.USAGE:
            if chunk.usage:
                print(f"\n[Usage] Prompt: {chunk.usage.prompt_tokens}, "
                      f"Completion: {chunk.usage.completion_tokens}, "
                      f"Total: {chunk.usage.total_tokens}")
        elif chunk.type == StreamChunk.ChunkType.DONE:
            print()  # 换行

    async def shutdown(self) -> None:
        self._running = False

@simple_tui_handlers.handler()
class UIHandler(EventHandler):
    """监听 Core 发出的 UI 输出事件，实时更新界面"""

    def __init__(self):
        super().__init__(["ui.output.text", "ui.output.stream", "ui.output.done", 'ui.start', 'ui.exit'])
        self.ui: Optional[ConsoleUI] = None
        self.ui_task: Optional[asyncio.Task[None]] = None

    async def handle(self, payload: BaseModel | None, bus_proxy: EventBus.Proxy, raw_event: Event):
        if raw_event.name == 'ui.start' and payload is None:
            self.ui = ConsoleUI(bus_proxy.bus)
            self.ui_task = asyncio.create_task(self.ui.run())
        if raw_event.name == 'ui.exit' and payload is None:
            assert self.ui_task is not None
            if not self.ui_task.done():
                self.ui_task.cancel()
                try:
                    await self.ui_task
                except asyncio.CancelledError:
                    pass

        if raw_event.name == "ui.output.text" and isinstance(payload, UIOutputTextPayload):
            assert self.ui is not None
            self.ui.print_text(payload.text, payload.end)
        elif raw_event.name == "ui.output.stream" and isinstance(payload, UIOutputStreamChunk):
            assert self.ui is not None
            self.ui.print_stream_chunk(payload.chunk)
        elif raw_event.name == "ui.output.done":
            pass
