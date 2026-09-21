from langchain_openai import ChatOpenAI
from .config import settings


def get_llm(json_mode: bool = False) -> ChatOpenAI:
    """主 Agent LLM — qwen3.8-flash。

    用途：日常对话、工具调用、行程编排、意图解析、记忆提取。
    """
    kwargs = dict(
        model=settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=120,
        max_retries=2,
    )
    if json_mode:
        kwargs["temperature"] = 0.3
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    else:
        kwargs["temperature"] = 0.7
    return ChatOpenAI(**kwargs)


def get_reasoning_llm(json_mode: bool = False) -> ChatOpenAI:
    """深度推理 LLM — qwen3.8-27b。

    用途：复杂代码生成（WebGL / SVG / React 组件）、多步推理、
    需要高质量输出的子任务。
    """
    kwargs = dict(
        model=settings.reasoning_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=180,          # 27b 推理较慢，放宽超时
        max_retries=2,
    )
    if json_mode:
        kwargs["temperature"] = 0.3
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    else:
        kwargs["temperature"] = 0.6
    return ChatOpenAI(**kwargs)
