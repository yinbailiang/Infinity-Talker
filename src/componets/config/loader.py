"""
配置加载工具:支持 YAML/JSON 文件 + 环境变量 + 运行时覆盖
"""

import json
import yaml
from pathlib import Path
from typing import Union, Optional
from .settings import Settings


class ConfigLoader:
    """配置加载与管理工具"""
    
    @staticmethod
    def from_file(
        file_path: Union[str, Path],
        format: Optional[str] = None,
        **overrides
    ) -> Settings:
        """
        从文件加载配置
        
        :param file_path: 配置文件路径
        :param format: 文件格式 ('yaml'/'json')，None 时自动检测
        :param overrides: 运行时覆盖参数
        :return: Settings 实例
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        
        # 自动检测格式
        if format is None:
            format = path.suffix.lower().lstrip('.')
            if format not in ('yaml', 'yml', 'json'):
                raise ValueError(f"不支持的配置格式: {path.suffix}")
        
        # 读取文件
        with open(path, 'r', encoding='utf-8') as f:
            if format in ('yaml', 'yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        # 合并运行时覆盖
        if overrides:
            data = ConfigLoader._deep_merge(data, overrides)
        
        # 解析为 Settings
        return Settings(**data)
    
    @staticmethod
    def save_to_file(settings: Settings, file_path: Union[str, Path], format: str = "yaml"):
        """
        保存配置到文件(敏感信息会脱敏)
        
        :param settings: Settings 实例
        :param file_path: 输出路径
        :param format: 'yaml' 或 'json'
        """
        # 转换为字典(排除敏感字段)
        data = settings.model_dump(mode='json', exclude={'llm': {'api_key'}})
        
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            if format == 'yaml':
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            else:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并两个字典"""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result 
                and isinstance(result[key], dict) 
                and isinstance(value, dict)
            ):
                result[key] = ConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


# 快捷函数
def load_config(
    file_path: Union[str, Path],
    **overrides
) -> Settings:
    """
    加载配置的快捷函数
    """
    return ConfigLoader.from_file(file_path, **overrides)