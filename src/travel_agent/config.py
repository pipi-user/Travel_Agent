from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 这里定义的变量，会自动去 .env 文件里找同名的配置
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.7-flash-2026-07-15"
    user_id: str = "demo"

    # 告诉 pydantic 去读同目录上级或者项目根目录的 .env 文件
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# 实例化，这样别的文件可以直接 from .config import settings
settings = Settings()