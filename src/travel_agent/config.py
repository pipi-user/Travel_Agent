from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.7-flash-2026-07-15"
    amap_key: str = ""          
    tavily_api_key: str = ""     
    user_id: str = "demo"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()