import streamlit as st

st.set_page_config(page_title="旅游攻略 Agent", page_icon="🧭", layout="wide")
st.title("🧭 旅游攻略 Agent")
st.caption("Day0 空壳：前端已跑通，等 Day1 接 Agent")

with st.form("travel"):
    col1, col2, col3 = st.columns(3)
    with col1:
        origin = st.text_input("出发地", "深圳")
        budget = st.number_input("预算（元）", 1000, 50000, 5000, step=500)
    with col2:
        days = st.slider("天数", 1, 15, 5)
        month = st.slider("月份", 1, 12, 10)
    with col3:
        pace = st.selectbox("节奏", ["轻松", "适中", "紧凑"])
        companions = st.selectbox("同行", ["独自", "情侣", "朋友", "家庭"])

    preferences = st.multiselect("偏好", ["美食", "自然", "历史", "城市", "亲子", "摄影"], default=["美食", "自然"])
    submitted = st.form_submit_button("生成攻略", use_container_width=True)

if submitted:
    st.success("表单提交成功，Day1 将把这里接到 Agent。")
    st.json({
        "origin": origin, "budget": budget, "days": days,
        "month": month, "preferences": preferences,
        "pace": pace, "companions": companions,
    })