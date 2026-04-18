from pathlib import Path
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """大语言模型 API 配置"""
    
    # API 基础信息
    provider: str = Field(default="openai", description="LLM 供应商")
    api_key: SecretStr = Field(default=SecretStr(""),description="API Key")
    endpoint: str = Field(default="", description="API 端点")
    model: str = Field(default="", description="模型名称")
    
    thinking: Optional[bool] = Field(default=None, description="是否启用思考")
    # 推理参数
    max_new_tokens: int = Field(
        default=4096, ge=1, le=65536, description="最大生成令牌数"
    )
    temperature: Optional[float] = Field(
        default=None, ge=0.0, le=2.0, description="采样温度"
    )
    top_p: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="核采样阈值"
    )
    frequency_penalty: Optional[float] = Field(
        default=None, ge=-2.0, le=2.0, description="频率惩罚"
    )
    presence_penalty: Optional[float] = Field(
        default=None, ge=-2.0, le=2.0, description="存在惩罚"
    )
    
    # 请求参数
    timeout: float = Field(default=120.0, ge=1.0, description="请求超时时间(秒)")
    
    @field_validator('endpoint')
    @classmethod
    def strip_endpoint(cls, v: str) -> str:
        """自动去除端点末尾空格"""
        return str(v).strip()

    def get_api_key(self) -> str:
        """安全获取 API Key 明文"""
        return self.api_key.get_secret_value()

class SentenceSpiltterConfig(BaseModel):
    """句子分割服务配置"""
    # 服务端点
    base_url: str = Field(
        default="http://localhost:8003",
        description="句子分割服务基础 URL"
    )
    timeout: float = Field(default=180.0, ge=1.0, description="请求超时时间 (秒)")

class TTSConfig(BaseModel):
    """TTS 服务配置"""
    
    enable_spiltter: bool = Field(default=False, description="是否启用句子风格")
    spiltter: SentenceSpiltterConfig = Field(default_factory=SentenceSpiltterConfig)

    # 服务端点
    base_url: str = Field(
        default="http://localhost:8001",
        description="TTS 服务基础 URL"
    )
    
    # 接口路径
    characters_endpoint: str = Field(default="/characters", description="角色列表接口路径")
    stream_endpoint: str = Field(default="/tts/stream", description="流式合成接口路径")
    nonstream_endpoint: str = Field(default="/tts", description="非流式接口路径")
    status_endpoint: str = Field(default="/status", description="状态检查接口路径")
    timeout: float = Field(default=120.0, ge=1.0, description="TTS 请求超时时间 (秒)")
    
    # 构建完整 URL(属性)
    @property
    def url_characters(self) -> str:
        return f"{str(self.base_url).rstrip('/')}{self.characters_endpoint}"
    
    @property
    def url_stream(self) -> str:
        return f"{str(self.base_url).rstrip('/')}{self.stream_endpoint}"
    
    @property
    def url_nonstream(self) -> str:
        return f"{str(self.base_url).rstrip('/')}{self.nonstream_endpoint}"
    
    @property
    def url_status(self) -> str:
        return f"{str(self.base_url).rstrip('/')}{self.status_endpoint}"
    
    # 默认语音参数
    chunk_size: int = Field(default=16, ge=1, description="音频流分块大小")
    character: str = Field(default="絮雨-JP", description="默认角色名称")
    language: Literal["Chinese", "Japanese", "English", "Auto"] = Field(
        default="Chinese", description="默认语言"
    )
    sample_rate: int = Field(default=24000, description="输出采样率")
    timeout: float = Field(default=120.0, ge=1.0, description="请求超时(秒)")
    
    # 播放策略
    wait_full_sentence: bool = Field(
        default=True,
        description="是否等待完整句子再播放(避免卡顿但增加延迟)"
    )

class VADConfig(BaseModel):
    """VAD参数"""
    mode: int = Field(default=3, ge=0, le=3, description="VAD 模式")
    silence_threshold: float = Field(default=1.0, ge=0.1, description="静音判定阈值(秒)")
    threshold: float = Field(default= 0.5,ge = 0.0,le = 1.0,description="语音帧占比阈值 (0~1)")
    frame_duration:float = Field(default=0.02,ge=0,description="VAD 判定帧长度，单位秒")

class RecorderConfig(BaseModel):
    """语音采集器参数"""

    sample_rate: int = Field(default=16000, description="采样率")
    channels: int = Field(default=1, description="声道数")
    chunk_size: int = Field(default=320, description="块采样数")

class ASRConfig(BaseModel):
    """语音识别参数"""

    vad: VADConfig = Field(default_factory=VADConfig)
    recorder: RecorderConfig = Field(default_factory=RecorderConfig)

    # ASR服务客户端参数
    api_url: str = Field(default="http://127.0.0.1:8002", description="ASR 服务地址")
    timeout: float = Field(default=180.0, ge=1.0, description="ASR 请求超时时间 (秒)")
    language: str = Field(default="auto", description="默认识别语言")
    return_time_stamps: bool = Field(default=False, description="是否返回时间戳")

class LoggingConfig(BaseModel):
    """日志配置"""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="日志输出级别"
    )
    file_path: Path = Field(
        default=Path("logs/app.log"),
        description="日志文件路径(相对路径相对于项目根目录)"
    )
    to_console: bool = Field(
        default=False,
        description="是否同时输出到控制台"
    )
    max_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        description="单个日志文件最大字节数"
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        description="轮转备份文件数"
    )

class ToolsConfig(BaseModel):
    """工具配置"""
    
    tools_directory: Path = Field(
        default=Path("./tools"),
        description="工具目录路径(相对路径相对于项目根目录)"
    )

class Live2DConfig(BaseModel):
    """Live2D 服务配置"""

    # 表情生成模块配置
    expr_gen_llm: LLMConfig = Field(default_factory=LLMConfig)

    # 服务端点
    base_url: str = Field(
        default="http://localhost:8004",
        description="Live2D 控制服务基础 URL"
    )
    
    # API 路径
    path_status: str = Field(default="/status", description="状态检查接口路径")
    path_queue: str = Field(default="/queue", description="队列状态接口路径")
    path_expression: str = Field(default="/expression", description="表情控制接口路径")
    path_reset: str = Field(default="/reset", description="重置表情接口路径")
    
    # 请求参数
    timeout: float = Field(default=5.0, ge=0.1, description="HTTP 请求超时时间(秒)")
    default_interrupt: bool = Field(default=False, description="默认是否打断当前动画")
    
    @property
    def url_status(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path_status}"
    
    @property
    def url_queue(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path_queue}"
    
    @property
    def url_expression(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path_expression}"
    
    @property
    def url_reset(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path_reset}"

class ServicesConfig(BaseModel):
    enable_tts: bool = Field(default=False,description="启用TTS功能")
    tts: TTSConfig = Field(default_factory=TTSConfig)
    enable_asr: bool = Field(default=False,description="启用ASR功能")
    asr: ASRConfig = Field(default_factory=ASRConfig)
    enable_live2d: bool = Field(default=False,description="启用Live2D功能")
    live2d: Live2DConfig = Field(default_factory=Live2DConfig)

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

class AgentConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)

class AuditorConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)

class Settings(BaseSettings):
    """全局配置聚合类"""
    agent: AgentConfig = Field(default_factory=AgentConfig)
    auditor: AuditorConfig = Field(default_factory=AuditorConfig)
    services : ServicesConfig = Field(default_factory=ServicesConfig)
    
    # Pydantic Settings 配置
    model_config = SettingsConfigDict(
        env_file=".env",           # 自动加载 .env 文件
        env_file_encoding="utf-8",
        case_sensitive=False,      # 环境变量不区分大小写
        extra="ignore",            # 忽略未知字段
    )