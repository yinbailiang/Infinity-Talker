import logging
from abc import ABC, abstractmethod
from enum import Enum
import types
from typing import AsyncGenerator, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

from componets.config import LLMConfig

logger = logging.getLogger(__name__)

class ContentType(str, Enum):
    """支持的内容类型枚举"""
    TEXT = "text"
    IMAGE_URL = "image_url"

class MultiModalContent(BaseModel):
    """多模态消息内容单元"""
    type: ContentType = Field(description="内容类型")
    text: Optional[str] = Field(default=None, description="文本内容")
    image_url: Optional[str] = Field(default=None, description="图片/媒体 URL")
    
    @model_validator(mode='after')
    def validate_mutual_exclusion(self) -> 'MultiModalContent':
        """确保 text 和 image_url 互斥且与 type 匹配"""
        if self.type == ContentType.TEXT:
            if self.text is None:
                raise ValueError("text is required when type='text'")
            if self.image_url is not None:
                raise ValueError("image_url must be None when type='text'")
        elif self.type == ContentType.IMAGE_URL:
            if self.image_url is None:
                raise ValueError("image_url is required when type='image_url'")
            if self.text is not None:
                raise ValueError("text must be None when type='image_url'")
        return self

class MessageRole(str, Enum):
    """消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

class Message(BaseModel):
    """LLM 消息格式"""
    role: MessageRole = Field(description="消息角色")
    content: List[Union[str, MultiModalContent]] = Field(description="消息内容列表，支持多模态混合")

Messages = List[Message]

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