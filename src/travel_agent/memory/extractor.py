# LLM 提取用户特征
import json
from langchain_core.prompts import ChatPromptTemplate
from ..llm import get_llm

def extract_profile(user_message: str) -> dict:
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "从用户的话中提取特征，以纯JSON输出：allergies(过敏原列表), fears(恐惧症列表), dietary(饮食禁忌), pace_preference(节奏偏好)。没有的填[]或null。"),
        ("human", "{message}")
    ])
    chain = prompt | llm
    try:
        res = chain.invoke({"message": user_message})
        # 清理可能的 markdown 标记
        content = res.content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except:
        return {}