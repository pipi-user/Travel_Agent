from langchain_openai import ChatOpenAI
from .config import settings

def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.7,
        timeout=40,        # ⏱️ 新增：请求超时时间（秒），超过40秒直接报错
        max_retries=1,     # 🔄 新增：失败重试次数（默认是2，改成1减少等待）
    )