from ..llm import get_llm
from ..schemas import TripIntent, TimeAnchor
import json
import re

PROMPT = """你是旅游行程意图解析器。从用户的话中提取结构化信息，只输出 JSON。

【字段规则】
- mode: 固定 "target"
- must_visit: **所有提到的城市名和景点名**（如"成都重庆双城游"→["成都","重庆"]）
- days: 严格照抄用户说的天数
- pace: "轻松/适中/紧凑"，没提就"适中"
- origin: 出发地，没提就""
- budget: 预算数字，没提就 0
- preferences: 从["美食","自然","历史","城市","亲子","摄影","购物","夜生活"]里选
- companions: "独自/情侣/朋友/家庭/带父母"等
- special_notes: 特殊要求
- start_date: 出发日期（YYYY-MM-DD），没提就""
- end_date: 返回日期，没提就""
- return_time: 返回时间描述，如"第三天下午"
- anchors: **用户明确指定的固定事件列表**，每个元素：
  - day: 第几天（整数，1/2/3...，没指定填 null）
  - time_hint: 时间描述（如"25号下午14:00"、"晚上"）
  - event: 事件描述（如"抵达汕头站"、"看电影"、"吃宵夜"、"返回中山"）
  - location: 地点（如"汕头站"）
  - fixed: true 表示不可改动（如"高铁到站"），false 表示可微调时间（如"看电影"）

【示例1】我要去爬泰山，3天，节奏紧凑，从深圳出发，预算5000
输出：{{"mode":"target","must_visit":["泰山"],"days":3,"pace":"紧凑","origin":"深圳","budget":5000,"preferences":[],"companions":"","special_notes":"","start_date":"","end_date":"","return_time":"","anchors":[]}}

【示例2】想去西安看兵马俑，5天，轻松一点，带父母，有老人膝盖不好
输出：{{"mode":"target","must_visit":["西安","兵马俑"],"days":5,"pace":"轻松","origin":"","budget":0,"preferences":[],"companions":"带父母","special_notes":"老人膝盖不好","start_date":"","end_date":"","return_time":"","anchors":[]}}

【示例3】我在2026年中秋节三天想和一个朋友从中山石岐出发去汕头旅游，计划25号下午乘坐高铁到达最近的汕头站，然后晚上去看一个电影，吃一个宵夜，等第二天再开始正式参观，第三天下午就要返回，帮我规划路线和进行推荐
输出：{{"mode":"target","must_visit":["汕头"],"days":3,"pace":"适中","origin":"中山石岐","budget":0,"preferences":["美食"],"companions":"朋友","special_notes":"2026年中秋节","start_date":"2026-09-25","end_date":"2026-09-27","return_time":"第三天下午","anchors":[{{"day":1,"time_hint":"25号下午","event":"乘坐高铁抵达汕头站","location":"汕头站","fixed":true,"notes":"从中山石岐出发"}},{{"day":1,"time_hint":"晚上","event":"看电影","location":"","fixed":false,"notes":""}},{{"day":1,"time_hint":"晚上","event":"吃宵夜","location":"","fixed":false,"notes":""}},{{"day":2,"time_hint":"全天","event":"开始正式参观","location":"","fixed":false,"notes":""}},{{"day":3,"time_hint":"下午","event":"返回中山","location":"","fixed":true,"notes":""}}]}}

【示例4】去三亚躺平5天，预算8000，带小孩
输出：{{"mode":"target","must_visit":["三亚"],"days":5,"pace":"轻松","origin":"","budget":8000,"preferences":["亲子","自然"],"companions":"家庭","special_notes":"带小孩","start_date":"","end_date":"","return_time":"","anchors":[]}}

现在解析下面这句话，只输出 JSON，不要任何解释或 markdown 代码块：
输入：{user_text}
"""


def parse_intent(user_text: str) -> TripIntent:
    llm = get_llm()
    try:
        res = llm.invoke(PROMPT.format(user_text=user_text))
        content = res.content.strip()
        content = re.sub(r"^```(json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start:end + 1]
        data = json.loads(content)
        # 手动构造 anchors，避免 pydantic 报错
        anchors_data = data.pop("anchors", [])
        intent = TripIntent(**data)
        intent.anchors = [TimeAnchor(**a) for a in anchors_data if isinstance(a, dict)]
        return intent
    except Exception as e:
        print(f"[parse_intent] 解析失败：{e}")
        return TripIntent(mode="target")