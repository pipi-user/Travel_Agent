/**
 * 介绍页区块
 * 
 * 主文案 (书法字体) + 三大特色 (玻璃卡片框) + Model A/B 并排卡片
 * 配色参考 Designspiration 柔和粉/米色渐变
 * 
 * 滚动入场动画，每个卡片独立触发，依次出现
 */

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

/* ==================== 可调参数 ==================== */
const ANIM_THRESHOLD = 0.15   // 入场动画触发阈值 (0~1)
/* ================================================== */

// 三大特色
const FEATURES = [
  { num: '01', title: '双框架并行', desc: '灵感漫游 · 定向定制，各司其职' },
  { num: '02', title: '全程可视化', desc: '卡片、评分、地图、路线，一目了然' },
  { num: '03', title: '生态多平台联动', desc: '推荐一键跳转百度、小红书、抖音深度了解' },
]

// Model A - 灵感漫游
const MODEL_A_STEPS = [
  '输入出发地 · 预算 · 人数 · 旅游风格 · 偏好 · 年龄',
  '生成 6 个城市推荐卡片，含图片与适合度评分',
  '选择目的地后进入全流程行程规划',
]

// Model B - 定向定制
const MODEL_B_STEPS = [
  '输入出发地 · 预算 · 目的地',
  '标注必玩项目、必吃美食等核心偏好',
  '偏好作为重点关注，融入后续全部行程安排',
]

interface IntroProps {
  onExplore: () => void
  onCurate: () => void
}

// 滚动入场动画 Hook - 单个元素（每次进入视口都触发）
function useScrollReveal(threshold = ANIM_THRESHOLD) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let observer: IntersectionObserver | null = null
    // 延迟一帧再观察，确保浏览器先绘制初始隐藏状态
    const raf = requestAnimationFrame(() => {
      observer = new IntersectionObserver(
        ([entry]) => { setVisible(entry.isIntersecting) },
        { threshold }
      )
      observer.observe(el)
    })
    return () => { cancelAnimationFrame(raf); observer?.disconnect() }
  }, [threshold])

  return { ref, visible }
}

export default function IntroSection({ onExplore, onCurate }: IntroProps) {
  const navigate = useNavigate()
  const mainReveal = useScrollReveal()
  
  // 每个特色卡片独立触发
  const feat01Reveal = useScrollReveal()
  const feat02Reveal = useScrollReveal()
  const feat03Reveal = useScrollReveal()
  
  // Model A/B 独立触发
  const modelAReveal = useScrollReveal()
  const modelBReveal = useScrollReveal()

  const featureReveals = [feat01Reveal, feat02Reveal, feat03Reveal]

  return (
    <section id="section-intro" className="intro-section">
      {/* 主介绍文案 - 书法字体 */}
      <div ref={mainReveal.ref} className={`intro-main ${mainReveal.visible ? 'visible' : ''}`}>
        <h2 className="intro-headline">不替你决定去哪，<br />只为你更好地抵达</h2>
        <p className="intro-desc">
          Travel Agent 是一套以推荐与规划为核心的旅行智能体。它理解你的预算、喜好与节奏，
          把「做攻略」这件琐碎的事，交给一套清晰、可交互、可回路的决策流水线。
        </p>
      </div>

      {/* 三大特色 - 玻璃卡片框，每个卡片独立触发 */}
      <div className="intro-features">
        {FEATURES.map((f, i) => (
          <div
            key={f.num}
            ref={featureReveals[i].ref}
            className={`feature-card ${featureReveals[i].visible ? 'visible' : ''}`}
          >
            <span className="feature-num">{f.num}</span>
            <h3 className="feature-title">{f.title}</h3>
            <p className="feature-desc">{f.desc}</p>
          </div>
        ))}
      </div>

      {/* Model A/B 并排卡片，各自独立触发 */}
      <div className="models-row">
        {/* Model A */}
        <div ref={modelAReveal.ref} className={`model-card model-a ${modelAReveal.visible ? 'visible' : ''}`}>
          <span className="model-badge model-a-badge">MODEL A</span>
          <h2 className="model-title">
            灵感漫游 <span className="model-subtitle">/ EXPLORE</span>
          </h2>
          <p className="model-desc">
            当你还没有明确方向：仅凭几个描述你的「参数」，AI 便为你描绘出 6 座最值得探索的城市。
          </p>
          <ul className="model-steps">
            {MODEL_A_STEPS.map((step, i) => (
              <li key={i} className="model-step">
                <span className="step-dot step-dot-a" />
                {step}
              </li>
            ))}
          </ul>
          <button className="glass-cta model-a-cta" onClick={() => navigate('/inspire')}>
            进入灵感漫游 <span>→</span>
          </button>
        </div>

        {/* Model B */}
        <div ref={modelBReveal.ref} className={`model-card model-b ${modelBReveal.visible ? 'visible' : ''}`}>
          <span className="model-badge model-b-badge">MODEL B</span>
          <h2 className="model-title">
            定向定制 <span className="model-subtitle">/ CURATE</span>
          </h2>
          <p className="model-desc">
            当你目标明确：直接给定出发地、目的地与预算，把「必玩的项目」与「必吃的美食」作为焦点注入行程。
          </p>
          <ul className="model-steps">
            {MODEL_B_STEPS.map((step, i) => (
              <li key={i} className="model-step">
                <span className="step-dot step-dot-b" />
                {step}
              </li>
            ))}
          </ul>
          <button className="glass-cta model-b-cta" onClick={() => navigate('/target')}>
            进入定向定制 <span>→</span>
          </button>
        </div>
      </div>
    </section>
  )
}
