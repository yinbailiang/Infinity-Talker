import asyncio
import json
import types
import logging
from typing import Any, AsyncGenerator, Literal, Optional, Dict, List

import aiohttp
from pydantic import BaseModel, Field

from . import LLMClient, Messages, StreamChunk, UsageStats
from ..exceptions import LLMNetworkError, LLMStreamError, build_http_error

logger = logging.getLogger(__name__)

class ChatCompletionTokenLogprob(BaseModel):
    """单个 token 的对数概率信息"""
    token: str = Field(description="Token 字符串")
    bytes: Optional[List[int]] = Field(default=None, description="Token 的字节表示")
    logprob: float = Field(description="Token 的对数概率")
    top_logprobs: Optional[List["ChatCompletionTokenLogprob"]] = Field(
        default=None,
        description="最可能的替代 token 列表"
    )

class LogprobsContent(BaseModel):
    """消息内容 token 的对数概率列表"""
    content: Optional[List[ChatCompletionTokenLogprob]] = Field(
        default=None,
        description="消息内容 token 的对数概率信息"
    )
    refusal: Optional[List[ChatCompletionTokenLogprob]] = Field(
        default=None,
        description="消息拒绝 token 的对数概率信息"
    )

class Delta(BaseModel):
    """流式返回的 completion 增量"""
    content: Optional[str] = Field(default=None, description="增量的文本内容")
    role: Optional[Literal["assistant"]] = Field(default=None, description="消息角色")
    function_call: Optional[Dict[Any, Any]] = Field(default=None, description="函数调用信息（已弃用）")
    refusal: Optional[str] = Field(default=None, description="拒绝消息内容")
    tool_calls: Optional[List[Dict[Any, Any]]] = Field(default=None, description="工具调用信息")

class CompletionTokensDetails(BaseModel):
    """completion 中 token 的细分统计"""
    accepted_prediction_tokens: Optional[int] = Field(
        default=None,
        description="使用预测输出时，预测中出现在 completion 中的 token 数量"
    )
    audio_tokens: Optional[int] = Field(
        default=None,
        description="模型生成的音频 token 数量"
    )
    reasoning_tokens: Optional[int] = Field(
        default=None,
        description="模型用于推理的 token 数量"
    )
    rejected_prediction_tokens: Optional[int] = Field(
        default=None,
        description="使用预测输出时，预测中未出现在 completion 中的 token 数量"
    )

class PromptTokensDetails(BaseModel):
    """prompt 中 token 的细分统计"""
    audio_tokens: Optional[int] = Field(
        default=None,
        description="prompt 中的音频 token 数量"
    )
    cached_tokens: Optional[int] = Field(
        default=None,
        description="prompt 中的缓存 token 数量"
    )

class CompletionUsage(BaseModel):
    """Token 使用统计"""
    completion_tokens: int = Field(description="生成的 completion 的 token 数量")
    prompt_tokens: int = Field(description="prompt 的 token 数量")
    total_tokens: int = Field(description="总计 token 数量")
    completion_tokens_details: Optional[CompletionTokensDetails] = Field(
        default=None,
        description="completion token 的细分信息"
    )
    prompt_tokens_details: Optional[PromptTokensDetails] = Field(
        default=None,
        description="prompt token 的细分信息"
    )

class Choice(BaseModel):
    """completion 选择项"""
    delta: Delta = Field(description="流式增量内容")
    finish_reason: Optional[Literal[
        "stop",
        "length",
        "content_filter",
        "tool_calls",
        "function_call"
    ]] = Field(
        default=None,
        description="模型停止生成 token 的原因"
    )
    index: int = Field(description="选择项的索引")
    logprobs: Optional[LogprobsContent] = Field(
        default=None,
        description="该 choice 的对数概率信息"
    )

class StreamEvent(BaseModel):
    """OpenAI 兼容流式响应的单个数据块"""
    id: str = Field(description="对话的唯一标识符，每个 chunk 相同")
    choices: List[Choice] = Field(
        description="completion 选择列表，若 n>1 可包含多个元素；若设置了 include_usage，最后 chunk 可能为空"
    )
    created: int = Field(description="创建时间戳（秒）")
    model: str = Field(description="模型名称")
    object: Literal["chat.completion.chunk"] = Field(
        default="chat.completion.chunk",
        description="对象类型，固定为 chat.completion.chunk"
    )
    service_tier: Optional[Literal["auto", "default", "flex", "scale", "priority"]] = Field(
        default=None,
        description="实际处理请求的服务层级"
    )
    system_fingerprint: Optional[str] = Field(
        default=None,
        description="后端配置指纹，可用于确定性调试"
    )
    usage: Optional[CompletionUsage] = Field(
        default=None,
        description="仅在 stream_options.include_usage 为 true 时存在，通常最后 chunk 包含完整统计"
    )

class OpenAIClient(LLMClient):
    """OpenAI 兼容 API 的轻量异步客户端（并发安全，严格类型）"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 60.0, connect_timeout: float = 10.0, include_usage: bool = True) -> None:
        self.api_key: str = api_key
        self.base_url: str = base_url.rstrip("/")
        self.model: str = model
        self.timeout: float = timeout
        self.connect_timeout: float = connect_timeout
        self.include_usage: bool = include_usage

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock: asyncio.Lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """懒初始化 ClientSession，保证并发安全。"""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout_config = aiohttp.ClientTimeout(
                    total=None,  # 流式请求禁用总超时
                    sock_connect=self.connect_timeout,
                    sock_read=self.timeout,
                )
                self._session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout_config,
                )
                logger.debug("Created new aiohttp ClientSession")
            return self._session

    async def close(self) -> None:
        """关闭底层 HTTP 会话。"""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                logger.debug("Closed aiohttp ClientSession")
            self._session = None

    async def __aenter__(self) -> "OpenAIClient":
        await self._ensure_session()  # 确保进入上下文时会话已就绪
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> Optional[bool]:
        await self.close()

    async def _request(self, endpoint: str, payload: Dict[str, Any]) -> aiohttp.ClientResponse:
        session: aiohttp.ClientSession = await self._ensure_session()
        url: str = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp: aiohttp.ClientResponse = await session.post(url, json=payload)
        except asyncio.TimeoutError as e:
            raise LLMNetworkError(f"Request timeout: {e}", original_error=e) from e
        except aiohttp.ClientError as e:
            raise LLMNetworkError(f"Connection error: {e}", original_error=e) from e

        if resp.status != 200:
            error_text = await resp.text()
            # 使用工具函数构建异常
            raise build_http_error(
                status_code=resp.status,
                message=f"API error {resp.status}: {error_text}",
                response_body=error_text,
            )

        return resp

    async def stream_chat(self, messages: Messages) -> AsyncGenerator[StreamChunk, None]:
        """流式对话，逐块产出 StreamChunk（TEXT / USAGE / FINISH / DONE）。"""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
        }
        if self.include_usage:
            payload["stream_options"] = {"include_usage": True}

        resp: aiohttp.ClientResponse = await self._request("chat/completions", payload)

        try:
            while True:
                try:
                    line_bytes: bytes = await resp.content.readline()
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    raise LLMNetworkError(f"Stream read error: {e}", original_error=e) from e
                
                if line_bytes == b'':
                    yield StreamChunk(type=StreamChunk.ChunkType.DONE)
                    break

                line: str = line_bytes.decode("utf-8").strip()
                if line.startswith(":"):
                    continue
                if not line.startswith("data: "):
                    logger.debug(f"Ignoring non-data SSE line: {line}")
                    continue
                if line == "data: [DONE]":
                    yield StreamChunk(type=StreamChunk.ChunkType.DONE)
                    break

                data_str: str = line[5:].strip()
                try:
                    event = StreamEvent(**json.loads(data_str))
                except json.JSONDecodeError as e:
                    # 流式 JSON 解析失败：抛出异常，中断生成器
                    raise LLMStreamError(
                        f"JSON decode error in stream: {e}",
                        original_error=e,
                        response_body=data_str,
                    ) from e



                if event.choices:
                    choice: Choice = event.choices[0]
                    if choice.delta.content:
                        yield StreamChunk(type=StreamChunk.ChunkType.TEXT, text=choice.delta.content)

                    if choice.finish_reason is not None:
                        yield StreamChunk(
                            type=StreamChunk.ChunkType.FINISH,
                            finish_reason=choice.finish_reason,
                        )
                
                if event.usage:
                    yield StreamChunk(
                        type=StreamChunk.ChunkType.USAGE,
                        usage=UsageStats(
                            prompt_tokens=event.usage.prompt_tokens,
                            completion_tokens=event.usage.completion_tokens,
                            total_tokens=event.usage.total_tokens,
                        ),
                    )
                
        finally:
            resp.close()