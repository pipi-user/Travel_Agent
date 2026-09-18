from langchain_core.tools import tool
import numexpr

@tool
def calculator(expression: str) -> str:
    """用于计算数学表达式，例如 (1200+300)*2 或 5000/5。"""
    try:
        return str(numexpr.evaluate(expression).item())
    except Exception as e:
        return f"计算失败：{e}"