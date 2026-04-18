"""
配置模块

提供应用程序的配置管理和加载功能。
"""

from .settings import (
    Settings,
    LLMConfig,
    TTSConfig,
    ASRConfig,
    VADConfig,
    SentenceSpiltterConfig,
    RecorderConfig,
    LoggingConfig,
    ToolsConfig,
    ServicesConfig,
    AgentConfig,
    AuditorConfig,
)
from .loader import load_config

__all__ = [
    "Settings",
    "LLMConfig",
    "TTSConfig",
    "ASRConfig",
    "VADConfig",
    "SentenceSpiltterConfig",
    "RecorderConfig",
    "LoggingConfig",
    "load_config",
    "ToolsConfig",
    "ServicesConfig",
    "AgentConfig",
    "AuditorConfig",
]
