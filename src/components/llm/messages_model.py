from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator

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

MessageContent = Union[str, List[MultiModalContent]]

class MessageRole(str, Enum):
    """消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

class Message(BaseModel):
    """LLM 消息格式"""
    role: MessageRole = Field(description="消息角色")
    content: MessageContent = Field(description="消息内容列表，支持多模态混合")

Messages = List[Message]

def build_multimodal(raw_data: Dict[str, str]) -> MultiModalContent:
    match ContentType(raw_data["type"]):
        case ContentType.TEXT:
            return MultiModalContent(type=ContentType.TEXT, text=raw_data['text'])
        case ContentType.IMAGE_URL:
            return MultiModalContent(type=ContentType.IMAGE_URL, image_url=raw_data['image_url'])
        case _:
            raise ValueError('Unknow multimodal content.')

def build_content(raw_data: Union[str, List[Dict[str, str]]]) -> MessageContent:
    if isinstance(raw_data, str):
        return raw_data
    return [build_multimodal(c) for c in raw_data]

def build_message(raw_data: Dict[str, Union[str, Union[str, List[Dict[str, str]]]]]) -> Message:
    return Message(
        role=MessageRole(raw_data["role"]),
        content=build_content(raw_data['content'])
    )

def build_messages(raw_data: List[Dict[str, Union[str, Union[str, List[Dict[str, str]]]]]]) -> Messages:
    return [build_message(msg) for msg in raw_data]