import streamlit as st
from travel_agent.graph import build_graph

st.set_page_config(page_title="旅游攻略 Agent", page_icon="🧭", layout="wide")
st.title("🧭 旅游攻略 Agent")
st.caption("Day1：已接入 Qwen 模型，可生成目的地推荐")

with st.form("travel"):
    col1, col2, col3 = st.columns(3)
    with col1:
        origin = st.text_input("出发地", "深圳")
        budget = st.number_input("预算（元）", 1000, 50000, 5000, step=500)
    with col2:
        days = st.slider("天数", 1, 15, 5)
        month = st.slider("月份", 1, 12, 7)
    with col3:
        pace = st.selectbox("节奏", ["轻松", "适中", "紧凑"])
        companions = st.selectbox("同行", ["独自", "情侣", "朋友", "家庭"])

    preferences = st.multiselect("偏好", ["美食", "自然", "历史", "城市", "亲子", "摄影"], default=["美食", "自然"])
    submitted = st.form_submit_button("生成攻略", use_container_width=True)

if submitted:
    with st.spinner("Agent 正在思考..."):
        graph = build_graph()
        result = graph.invoke({
            "request": {
                "origin": origin,
                "budget": budget,
                "days": days,
                "month": month,
                "preferences": preferences,
                "pace": pace,
                "companions": companions,
            },
            "candidates": [],
            "selected_city": None,
            "itinerary": None,
        })

    st.success("推荐生成成功！")
    for city in result["candidates"]:
        with st.container(border=True):
            st.subheader(f"📍 {city['city']}  ⭐ {city['score']}/10")
            st.write(f"**推荐理由**：{city['reason']}")
            st.write(f"**预估花费**：{city['estimated_cost']} 元/人")
            st.write(f"**当季天气**：{city['weather']}")