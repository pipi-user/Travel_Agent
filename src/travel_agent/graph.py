#用 LangGraph 把流程串起来
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate
from .state import TravelState
from .schemas import TravelRequest, DestinationList
from .llm import get_llm

def parse_request(state: TravelState) -> dict:
    """把前端表单转成结构化数据"""
    req = TravelRequest(**state["request"])
    return {"request": req.model_dump()}

def recommend_destinations(state: TravelState) -> dict:
    """根据需求推荐 3 个城市"""
    llm = get_llm()
    # 使用 json_mode 兼容 qwen
    structured_llm = llm.with_structured_output(DestinationList, method="json_mode")

    prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "你是一个资深旅游规划师。根据用户需求推荐3个目的地城市。"
         "请以 JSON 格式输出，包含 destinations 数组。"
         "每个城市给出：城市名(city)、推荐理由(reason，限30字内)、评分(score)、预估花费(estimated_cost)、天气(weather)。"),  # 👈 限制了30字
        ("human", "出发地：{origin}\n预算：{budget}元\n天数：{days}天\n月份：{month}月\n偏好：{preferences}\n节奏：{pace}\n同行：{companions}"),
    ])

    chain = prompt | structured_llm
    result = chain.invoke(state["request"])
    return {"candidates": [d.model_dump() for d in result.destinations]}

def format_output(state: TravelState) -> dict:
    """Day1 先空着，Day3 再丰富"""
    return {}

def build_graph():
    builder = StateGraph(TravelState)
    builder.add_node("parse", parse_request)
    builder.add_node("recommend", recommend_destinations)
    builder.add_node("format", format_output)

    builder.add_edge(START, "parse")
    builder.add_edge("parse", "recommend")
    builder.add_edge("recommend", "format")
    builder.add_edge("format", END)

    return builder.compile()