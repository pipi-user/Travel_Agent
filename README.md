# 🌍 Travel Agent — AI 智能旅行规划系统

> 像聊天一样规划旅行。双模式对话引擎 · 实时流式输出 · 拖拽式行程编辑 · 跨会话记忆

```
travel_agent/                    ← GitHub 仓库根目录
├── src/travel_agent/            ← 后端 Python 源码（FastAPI + LangGraph）
├── data/                        ← 城市数据 + 图片（运行时自动生成缓存）
├── travel-agent-web/            ← 前端（React 19 + Vite）
│   └── src/
├── .env.example                 ← 环境变量模板
└── pyproject.toml               ← Python 依赖配置
```

---

## ✨ 特性

| 特性 | 说明 |
|------|------|
| 🎯 **双模式对话引擎** | **灵感漫游**（不知道去哪 → 城市推荐 → 行程生成）与 **定向定制**（已知目的地 → 需求采集 → 行程生成）两条完整路径 |
| 🧠 **跨会话记忆系统** | SQLite + sqlite-vec 向量存储，记住用户的过敏/恐惧/饮食禁忌/节奏偏好，下次规划自动注入 |
| 🔄 **LangGraph 状态机** | 对话流程建模为有向图（greeting → extract_info → research → collect_pois → rag_search → generate_itinerary），支持指代消解、季节感知 |
| ⚡ **SSE 实时流式输出** | 逐 token 输出对话文本，工具调用过程全可视化（采集进度、搜索状态、推理步骤） |
| 🗺️ **高德地图深度集成** | POI 搜索（景点/美食/酒店）、路线规划、交通时间计算，数据源可靠 |
| 🎨 **WebGL 液态玻璃 UI** | 原生 WebGL Fragment Shader 实现全屏液态折射背景 + 玻璃态卡片设计 |
| 🖱️ **拖拽式行程编辑** | @dnd-kit 实现景点自由拖拽换序，选酒店自动重新规划，实时预算计算 |
| 💰 **智能预算控制** | 住宿 40% / 餐饮 35% / 景点 15% / 交通 10% 分项配额，允许 10% 浮动缓冲 |
| 📍 **RAG 语义检索** | POI 向量化索引，用户偏好语义匹配，命中的景点优先排入行程 |

---

## 🏗️ 技术栈

### 后端

| 层级 | 技术 |
|------|------|
| Web 框架 | **FastAPI** + Uvicorn |
| Agent 编排 | **LangGraph** 状态机 + LangChain |
| LLM | **Qwen3.7-Flash**（日常）/ **Qwen3.8-27B**（推理） |
| Embedding | 阿里百炼 **text-embedding-v3**（1024 维） |
| 向量存储 | **sqlite-vec**（用户记忆 + POI 语义索引） |
| 缓存 | **SQLite** 持久化缓存（城市 POI 池 30 天有效） |
| 地图服务 | **高德地图 API**（POI 搜索 / 路线规划 / 天气查询） |
| 图片搜索 | **Tavily API** |
| HTTP 客户端 | **httpx**（异步） |

### 前端

| 层级 | 技术 |
|------|------|
| 框架 | **React 19** + **TypeScript** |
| 构建 | **Vite 8** |
| 路由 | **React Router v7** |
| 拖拽 | **@dnd-kit** |
| 地图 | **@amap/amap-jsapi-loader** |
| 背景 | 原生 **WebGL** Fragment Shader |
| 流式通信 | **EventSource**（SSE） |

---

## 📐 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Frontend (React 19)                       │
│  ┌─────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │  Home   │ │ InspireChat  │ │ TargetChat   │ │ Workshop │ │
│  │  Landing│ │   Page       │ │   Page       │ │   Page   │ │
│  └────┬────┘ └──────┬───────┘ └──────┬───────┘ └────┬─────┘ │
│       │              │ SSE            │ SSE           │       │
│       └──────────────┴────────────────┴───────────────┘       │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────┴───────────────────────────────┐
│                    Backend (FastAPI)                           │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ /api/inspire │  │ /api/target  │  │ /api/explore        │ │
│  │  灵感漫游    │  │  定向定制    │  │  城市推荐 + POI 池  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘ │
│         │                  │                      │            │
│  ┌──────┴──────────────────┴──────────────────────┴──────────┐│
│  │              LangGraph 状态机引擎                          ││
│  │  greeting → extract_info → check → ask_question           ││
│  │                         ↓ complete                        ││
│  │  research → collect_pois → rag_search → generate_itinerary││
│  └──────────────────────────┬────────────────────────────────┘│
│                              │                                 │
│  ┌───────────┐  ┌───────────┴──┐  ┌────────────────────────┐ │
│  │  Memory   │  │   Agents     │  │      Tools             │ │
│  │  System   │  │              │  │                        │ │
│  │ ┌───────┐ │  │ ┌──────────┐ │  │ ┌────────────────────┐ │ │
│  │ │画像DB │ │  │ │destination│ │  │ │ 高德 API (POI/路线)│ │ │
│  │ │向量记忆│ │  │ │poi_collect│ │  │ │ Tavily (图片搜索)  │ │ │
│  │ │POI 索引│ │  │ │itinerary │ │  │ │ 预算过滤           │ │ │
│  │ └───────┘ │  │ │planner   │ │  │ │ 偏好评分           │ │ │
│  └───────────┘  │ └──────────┘ │  │ └────────────────────┘ │ │
│                 └──────────────┘  └────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

### 后端（根目录）

```
travel_agent/
├── src/travel_agent/
│   ├── api/                        # FastAPI 路由层
│   │   ├── app.py                  # 主入口，注册 5 个路由模块
│   │   ├── models.py               # Pydantic 请求/响应模型
│   │   └── routes/
│   │       ├── inspire.py          # 灵感漫游对话 API（SSE 流式）
│   │       ├── target_chat.py      # 定向定制对话 API（SSE 流式）
│   │       ├── explore.py          # 城市推荐 + POI 池获取
│   │       ├── plan.py             # 路线规划（高德方向 API）
│   │       └── memory.py           # 记忆管理（画像/向量/标记）
│   │
│   ├── agents/                     # 核心 Agent 模块
│   │   ├── destination.py          # 城市推荐 v3（372 城 + Haversine 距离 + 预算过滤）
│   │   ├── poi_collector.py        # POI 池采集 v4（高德 + LLM 打标 + 30 天缓存）
│   │   ├── itinerary_planner.py    # 行程编排 v7（时段分配 + 地理就近 + 餐食匹配）
│   │   ├── budget_filter.py        # 预算硬过滤（分项配额）
│   │   ├── preference_scorer.py    # 偏好标签权重排序
│   │   ├── city_meta.py            # 城市元数据 + 距离计算
│   │   └── itinerary_agent.py      # 行程调整 Agent（LLM 意图解析 + 代码执行）
│   │
│   ├── memory/                     # 记忆系统
│   │   ├── store.py                # 用户画像（SQLite：过敏/恐惧/饮食/节奏）
│   │   ├── vector_store.py         # 向量记忆（sqlite-vec：liked/disliked/visited）
│   │   ├── poi_vector_store.py     # POI 语义索引（sqlite-vec：景点/美食/酒店）
│   │   ├── embeddings.py           # Embedding（阿里百炼 text-embedding-v3）
│   │   └── memory_agent.py         # 记忆统一出口（检索/提取/注入）
│   │
│   ├── inspire_graph.py            # 灵感漫游 LangGraph 状态机
│   ├── target_graph.py             # 定向定制 LangGraph 状态机
│   ├── llm.py                      # 双 LLM 配置（flash + 27b）
│   ├── config.py                   # 配置管理（.env）
│   ├── schemas.py                  # 领域数据模型
│   ├── cache.py                    # SQLite 持久化缓存
│   └── evaluation.py               # 行程质量评估
│
├── data/                           # 数据目录
│   ├── cities.json                 # 372 城市坐标
│   ├── city_meta.json              # LLM 生成的城市画像
│   ├── cache.db                    # 持久化缓存
│   ├── travel_memory.db            # 用户画像数据库
│   ├── memory_vec.db               # 向量记忆数据库
│   └── poi_vec.db                  # POI 向量索引库
│
├── .env.example                 ← 环境变量模板
└── pyproject.toml               ← Python 依赖配置
```

### 前端 `travel-agent-web/`

```
travel-agent-web/
├── src/
│   ├── App.tsx                     # 主应用（React Router v7 路由配置）
│   ├── main.tsx                    # 入口
│   │
│   ├── pages/                      # 页面组件
│   │   ├── InspireChatPage.tsx     # 灵感漫游对话页（SSE + 城市卡片）
│   │   ├── TargetChatPage.tsx      # 定向定制对话页（信息收集进度条）
│   │   ├── WorkshopPage.tsx        # 拖拽自定义工作台（酒店选择 + 行程调整）
│   │   ├── RoutePage.tsx           # 行程详情页（时间轴 + 交通路线）
│   │   ├── ExplorePage.tsx         # 城市推荐页
│   │   └── PlannerPage.tsx         # 行程规划页
│   │
│   ├── components/                 # 通用组件
│   │   ├── WebGLBackground.tsx     # WebGL 液态玻璃背景（Simplex 噪声 + 鼠标交互）
│   │   ├── HeroSection.tsx         # Hero 首屏（背景图轮播 + 书法字体 + 视差）
│   │   ├── IntroSection.tsx        # 介绍页（三大特色 + Model A/B 卡片）
│   │   ├── AboutSection.tsx        # 关于页
│   │   ├── Navbar.tsx              # 顶部导航（IntersectionObserver 滚动高亮）
│   │   ├── GlassButton.tsx         # 磨砂玻璃态按钮
│   │   ├── POICard.tsx             # POI 卡片组件
│   │   ├── CityCard.tsx            # 城市推荐卡片
│   │   ├── AmapView.tsx            # 高德地图组件
│   │   └── POIDetailModal.tsx      # POI 详情弹窗
│   │
│   └── api/
│       └── explore.ts              # 前端 API 客户端
│
└── package.json
```

---

## 🚀 快速启动

### 环境要求

- Python ≥ 3.13
- Node.js ≥ 18
- UV 包管理器（推荐）

### 1. 克隆项目

```bash
git clone <repo-url>
cd <repo-name>              # 进入克隆下来的项目目录
```

### 2. 后端启动

```bash
# 安装 Python 依赖（推荐 UV）
uv sync

# 配置环境变量（复制模板，填入你的 API Key）
cp .env.example .env
# 必填：OPENAI_API_KEY（兼容OPENAI）、AMAP_KEY（高德地图）
# 可选：TAVILY_API_KEY（图片搜索）

# 启动后端服务（默认端口 8000）
uv run uvicorn travel_agent.api.app:app --reload
```

### 3. 前端启动

```bash
cd travel-agent-web

# 安装 Node 依赖
npm install

# 启动前端开发服务器（默认端口 5173）
npm run dev
```

访问 `http://localhost:5173` 即可使用。

> **提示**：前端通过 `http://localhost:8000` 调用后端 API，确保后端先启动。

---

## 🔄 核心流程

### 灵感漫游（Inspire Flow）

> 适合不知道去哪里的用户，通过对话推荐城市并生成行程。

```
用户输入 → 正则+LLM 双层提取 → 信息完整？
                                    ├─ 否 → LLM 流式追问
                                    └─ 是 ↓
                              城市推荐（372 城打分 → Top 6）
                                    ↓
                              用户选择城市
                                    ↓
                          POI 采集（高德 + LLM 打标）
                                    ↓
                          RAG 语义检索（偏好匹配）
                                    ↓
                          行程编排（时段分配 + 就近匹配）
                                    ↓
                          流式输出行程卡片
                                    ↓
                     工作台拖拽编辑 → 确认路线 → 沉淀记忆
```

### 定向定制（Target Flow）

> 用户已知目的地，Agent 主动采集需求并生成行程。

```
用户输入 → P6 指代消解 → 正则+LLM 双层提取 → 信息完整？
                                                  ├─ 否 → LLM 流式追问
                                                  └─ 是 ↓
                                        Agent 工具调用（研究目的地特色）
                                                  ↓
                                        POI 采集（高德 + LLM 打标）
                                                  ↓
                                        RAG 语义检索
                                                  ↓
                                        行程编排 + 流式输出
                                                  ↓
                                        工作台编辑 → 确认 → 记忆沉淀
```

---

## 🧠 记忆系统

记忆系统分为三层，统一由 `memory_agent.py` 出口管理：

| 层级 | 存储 | 内容 | 用途 |
|------|------|------|------|
| **用户画像** | `travel_memory.db`（SQLite） | 过敏/恐惧/饮食禁忌/节奏偏好 | 硬约束注入 LLM Prompt |
| **向量记忆** | `memory_vec.db`（sqlite-vec） | liked/disliked/visited/preference/note | 语义检索 Top-K，注入上下文 |
| **POI 索引** | `poi_vec.db`（sqlite-vec） | 景点/美食/酒店的向量表示 | RAG 偏好匹配，命中 POI 优先排入行程 |

**工作流：**
1. 对话开始 → `retrieve_context()` 拉取用户画像 + 向量记忆 → 注入 Prompt
2. 行程确认 → `extract_and_save()` LLM 提取值得记住的事实 → 写入向量库
3. 前端反馈 → `mark_liked/disliked/visited()` 快捷写入

---

## 📡 API 端点

### 灵感漫游 `/api/inspire`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话 |
| POST | `/chat/stream` | SSE 流式对话 |
| POST | `/adjust` | 行程调整 Agent |
| POST | `/feedback` | 用户反馈（点赞/踩） |

### 定向定制 `/api/target`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话 |
| POST | `/chat/stream` | SSE 流式对话 |
| POST | `/feedback` | 用户反馈 |

### 探索规划 `/api/explore`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/cities` | 推荐 6 座城市 |
| POST | `/pois` | 获取城市 POI 池 + 预生成行程 |
| POST | `/replan` | 根据选中酒店重新规划行程 |

### 路线规划 `/api/plan`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/route` | 批量计算交通路线 + 总预算 |

### 记忆管理 `/api/memory`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/{user_id}/profile` | 获取用户画像 |
| POST | `/{user_id}/profile` | 保存用户画像 |
| GET | `/{user_id}/memories` | 列出所有记忆 |
| POST | `/{user_id}/memories` | 批量写入记忆 |
| POST | `/{user_id}/search` | 语义检索 |
| POST | `/{user_id}/mark/liked` | 标记喜欢 |
| POST | `/{user_id}/mark/disliked` | 标记不喜欢 |
| POST | `/{user_id}/mark/visited` | 标记去过 |
| POST | `/{user_id}/extract` | 从行程中提取记忆 |

---

## ⚙️ 配置说明

在 `.env` 文件中配置以下环境变量：

```env
# 必填
OPENAI_API_KEY=your-api-key              
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AMAP_KEY=your-amap-key                   # 高德地图 API Key

# LLM 模型
MODEL=qwen3.7-flash-2026-07-15           # 主 Agent（日常对话/工具调用）
REASONING_MODEL=qwen3.8-27b              # 深度推理（复杂代码/WebGL）

# 可选
TAVILY_API_KEY=your-tavily-key           # Tavily 图片搜索
USER_ID=demo                             # 默认用户 ID
```

---

## 🎨 前端路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | HomePage | 首屏（WebGL 背景 + Hero + 介绍 + 关于） |
| `/inspire` | InspireChatPage | 灵感漫游对话 |
| `/target` | TargetChatPage | 定向定制对话 |
| `/workshop/:city` | WorkshopPage | 拖拽式行程编辑工作台 |
| `/route-result/:city` | RoutePage | 行程详情 + 交通路线 |
| `/explore` | ExplorePage | 城市推荐 |
| `/planner/:city` | PlannerPage | 行程规划 |

---

## 🔑 核心模块详解

### 城市推荐 `destination.py`

- 覆盖 **中国372 个城市**，Haversine 公式计算城际距离
- 单程票价估算（距离分段函数）
- **预算硬过滤**：交通费都付不起的直接淘汰
- 综合打分：`base_score + 偏好匹配 + 预算余量 + 距离加成`
- 取 Top 6，按排名映射展示分（9.8 → 7.8）
- LLM 生成 20 字城市简介 + Tavily 搜索城市风景图

### POI 采集 `poi_collector.py`

- **城市池缓存**：按城市采集，30 天有效，持久化到 SQLite
- **用户级过滤**：预算/人数/天数/偏好实时过滤，毫秒级
- 高德多关键词分页搜索（景点 10 词 / 美食 10 词 / 酒店 9 词）
- LLM 批量打标（8 条/批，3 并发，7 天缓存）
- 酒店房价估算（按类型 + 城市等级系数）
- Tavily 自动补图

### 行程编排 `itinerary_planner.py`

- 每天固定 **7 个站点**：早餐 1 + 上午景点 1 + 午餐 1 + 下午景点 2 + 晚餐 1 + 晚上景点 1
- **时段感知**：灯光秀/夜市 → 晚上，早市/日出 → 早上
- **餐食就近匹配**：早餐匹配早上景点附近，正餐匹配下午/晚上景点附近
- 贪心最近邻排序，同标签去重
- 可选传入酒店位置作为锚点优化排序

### 预算过滤 `budget_filter.py`

| 分项 | 配额 | 说明 |
|------|------|------|
| 住宿 | 40% | 酒店总价 ≤ 预算×40%×1.1 |
| 餐饮 | 35% | 单笔 ≤ 日预算×1.5 |
| 景点 | 15% | 单笔 ≤ 日预算×1.5 |
| 交通 | 10% | — |
| 缓冲 | +10% | 整体允许 10% 浮动 |

---

## 📊 数据流

```
用户自然语言输入
       ↓
┌─────────────────┐
│ 正则 + LLM 提取  │  双层提取，正则兜底
└────────┬────────┘
         ↓
┌─────────────────┐
│  记忆系统注入     │  画像 + 向量记忆 → Prompt
└────────┬────────┘
         ↓
┌─────────────────┐
│  城市推荐 / 研究  │  372 城打分 or 目的地特色搜索
└────────┬────────┘
         ↓
┌─────────────────┐
│  POI 池采集      │  高德 API → 去重 → LLM 打标 → 补图
└────────┬────────┘
         ↓
┌─────────────────┐
│  预算过滤 + 排序  │  分项配额 + 偏好加权
└────────┬────────┘
         ↓
┌─────────────────┐
│  RAG 语义检索    │  偏好 → 向量匹配 → 命中 POI 优先
└────────┬────────┘
         ↓
┌─────────────────┐
│  行程编排        │  时段分配 + 地理就近 + 餐食匹配
└────────┬────────┘
         ↓
┌─────────────────┐
│  SSE 流式输出    │  text_chunk + tool_call + quick_actions
└────────┬────────┘
         ↓
┌─────────────────┐
│  工作台拖拽编辑   │  选酒店 → 重新规划 / 拖拽换序 / 调整 Agent
└────────┬────────┘
         ↓
┌─────────────────┐
│  路线确认        │  高德方向 API 逐段计算交通 + 总预算
└────────┬────────┘
         ↓
┌─────────────────┐
│  记忆沉淀        │  LLM 提取 → 向量库写入
└─────────────────┘
```

---

## 🛠️ 开发指南

### 添加新的 Agent 模块

1. 在 `agents/` 目录创建新模块
2. 在对应的 `routes/` 文件中导入调用
3. 如需 LLM，使用 `from ...llm import get_llm` 获取实例

### 前端新增页面

1. 在 `pages/` 目录创建页面组件
2. 在 `App.tsx` 的 `<Routes>` 中添加路由
3. API 调用统一在 `api/explore.ts` 中封装

### 缓存策略

- 城市 POI 池：30 天（`POI_POOL_TTL`）
- LLM 打标结果：7 天（`TAG_CACHE_TTL`）
- 图片 URL：30 天（`IMG_CACHE_TTL`）
- Embedding 向量：7 天
- 池版本号 `POOL_VERSION`：改采集逻辑时递增，强制刷新旧缓存

---

## 📝 License

MIT
