import logging
from abc import ABC, abstractmethod
from enum import Enum
import types
from typing import AsyncGenerator,Optional
from pydantic import BaseModel, Field

from components.config import LLMConfig
from ..messages_model import Messages

logger = logging.getLogger(__name__)


class UsageStats(BaseModel):
    """LLM Token 使用统计"""
    prompt_tokens: int = Field(ge=0, description="输入令牌数")
    completion_tokens: int = Field(ge=0, description="输出令牌数")
    total_tokens: int = Field(ge=0, description="总令牌数")

class StreamChunk(BaseModel):
    """流式响应单元"""
    class ChunkType(str, Enum):
        TEXT = 'text'           # 正常文本片段
        USAGE = 'usage'         # 使用统计（通常在流结束时）
        FINISH = 'finish'       # 流结束理由（通常在流结束时）
        DONE = 'done'           # 流正常结束标记

    type: ChunkType = Field(description="片段类型")
    text: Optional[str] = Field(default=None, description="文本内容，仅 type='text' 时有效")
    finish_reason: Optional[str] = Field(default=None, description="结束理由，仅 type='finish' 时有效")
    usage: Optional[UsageStats] = Field(default=None, description="使用统计，仅 type='usage' 时有效")

class LLMClient(ABC):
    """LLM 客户端抽象基类"""

    @abstractmethod
    async def __aenter__(self) -> 'LLMClient':
        """支持 async with 资源管理"""
        pass
    
    @abstractmethod
    async def __aexit__(self, exc_type: Optional[type[BaseException]], 
                        exc_val: Optional[BaseException], 
                        exc_tb: Optional[types.TracebackType]) -> Optional[bool]:
        pass

    
    # ---------- 核心对话接口 ----------
    @abstractmethod
    def stream_chat(self, messages: Messages) ->  AsyncGenerator[StreamChunk, None]:
        """
        流式对话接口
        
        :param messages: 消息列表(统一为 List[MultiModalContent])
        :yield: StreamChunk 对象，调用方通过 chunk.type 分支处理
        :raise: LLMError
        """
        pass

from .open_ai_client import OpenAIClient

def create_llm_client(config: LLMConfig) -> LLMClient:
    """根据配置创建 LLM 客户端实例"""
    match config.provider:
        case "openai":
            return OpenAIClient(
                api_key=config.api_key.get_secret_value(),
                base_url=config.endpoint,
                model=config.model
            )
        case _:
            raise ValueError(f"Unsupported LLM provider: {config.provider}")