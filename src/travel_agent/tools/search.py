from langchain_core.tools import tool
from tavily import TavilyClient
from ..config import settings

@tool
def web_search(query: str) -> str:
    """搜索旅游攻略、最新景点信息、避坑指南。输入需要搜索的关键词。"""
    if not settings.tavily_api_key:
        return "未配置 Tavily API Key，无法使用搜索。"
    client = TavilyClient(api_key=settings.tavily_api_key)
    res = client.search(query, max_results=5)
    return "\n\n".join(
        f"【{r['title']}】\n{r['content'][:400]}"
        for r in res["results"]
    )