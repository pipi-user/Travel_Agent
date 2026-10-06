/**
 * Hero 首屏区块 - 最终版
 * 
 * 全屏背景图 + 大字体错位排版 + 动态右侧卡片
 * 字体大小层级分明、颜色丰富、布局错位有致
 * 右侧卡片随背景切换联动，点击可跳转
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import GlassButton from './GlassButton'

/* ==================== 可调参数 ==================== */
const PARALLAX_INTENSITY = 8     // 鼠标视差偏移量 px
const AUTO_SLIDE_INTERVAL = 6000 // 自动轮播间隔 ms
/* ================================================== */

// 背景图列表
const BACKGROUNDS = [
  '/backgrounds/bg-01.jpg',
  '/backgrounds/bg-06.jpg',
  '/backgrounds/bg-07.jpg',
  '/backgrounds/bg-08.jpg',
  '/backgrounds/bg-09.jpg',
  '/backgrounds/bg-11.jpg',
  '/backgrounds/bg-12.jpg',
]

// 轮播文案 - 每个配不同的右侧卡片（图片与地名严格对应）
const QUOTES = [
  { 
    title: '探索', 
    subtitle: '无界之旅', 
    quote: '"生活不是为了赶路，而是为了感受路。"', 
    location: '北京 · 天坛',
    cards: [
      { name: '北京 · 天坛', rating: 5, img: '/backgrounds/bg-01.jpg' },
      { name: '北京 · 十七孔桥', rating: 4, img: '/backgrounds/bg-06.jpg' },
    ]
  },
  { 
    title: '远方', 
    subtitle: '心之所向', 
    quote: '"等风来，不如追风去。"', 
    location: '新疆 · 夏塔',
    cards: [
      { name: '新疆 · 夏塔', rating: 5, img: '/backgrounds/bg-07.jpg' },
      { name: '洛阳 · 龙门石窟', rating: 5, img: '/backgrounds/bg-12.jpg' },
    ]
  },
  { 
    title: '山水', 
    subtitle: '自在行', 
    quote: '"山高路远，看世界 也找自己。"', 
    location: '九寨 · 海子',
    cards: [
      { name: '九寨 · 海子', rating: 5, img: '/backgrounds/bg-11.jpg' },
      { name: '西江 · 千户苗寨', rating: 4, img: '/backgrounds/bg-08.jpg' },
    ]
  },
  { 
    title: '自由', 
    subtitle: '随风而行', 
    quote: '"风吹又日晒，自由又自在。"', 
    location: '珠海 · 大剧院',
    cards: [
      { name: '珠海 · 大剧院', rating: 5, img: '/backgrounds/bg-09.jpg' },
      { name: '北京 · 天坛', rating: 4, img: '/backgrounds/bg-01.jpg' },
    ]
  },
  { 
    title: '出发', 
    subtitle: '步履不停', 
    quote: '"出发永远比向往更有意义。"', 
    location: '北京 · 十七孔桥',
    cards: [
      { name: '北京 · 十七孔桥', rating: 5, img: '/backgrounds/bg-06.jpg' },
      { name: '新疆 · 夏塔', rating: 4, img: '/backgrounds/bg-07.jpg' },
    ]
  },
  { 
    title: '旅途', 
    subtitle: '感受路', 
    quote: '"答案都在路上 自由都在风里。"', 
    location: '西江 · 千户苗寨',
    cards: [
      { name: '西江 · 千户苗寨', rating: 5, img: '/backgrounds/bg-08.jpg' },
      { name: '珠海 · 大剧院', rating: 4, img: '/backgrounds/bg-09.jpg' },
    ]
  },
  { 
    title: '世界', 
    subtitle: '那么大', 
    quote: '"那些要去的地方，都是素未谋面的故乡。"', 
    location: '洛阳 · 龙门石窟',
    cards: [
      { name: '洛阳 · 龙门石窟', rating: 5, img: '/backgrounds/bg-12.jpg' },
      { name: '九寨 · 海子', rating: 5, img: '/backgrounds/bg-11.jpg' },
    ]
  },
]

interface HeroProps {
  onExplore: () => void
}

export default function HeroSection({ onExplore }: HeroProps) {
  const [slide, setSlide] = useState(0)
  const [mouse, setMouse] = useState({ x: 0, y: 0 })
  const [scrollProgress, setScrollProgress] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 自动轮播
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setSlide(s => (s + 1) % BACKGROUNDS.length)
    }, AUTO_SLIDE_INTERVAL)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  // 切换幻灯片时触发动画
  useEffect(() => {
    setIsAnimating(true)
    const timer = setTimeout(() => setIsAnimating(false), 1000)
    return () => clearTimeout(timer)
  }, [slide])

  // 鼠标视差
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * 2
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * 2
    setMouse({ x, y })
  }, [])

  // 滚动进度追踪
  useEffect(() => {
    const handleScroll = () => {
      if (!containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const sectionHeight = rect.height
      const scrolled = -rect.top
      const progress = Math.min(Math.max(scrolled / (sectionHeight * 0.5), 0), 1)
      setScrollProgress(progress)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const q = QUOTES[slide % QUOTES.length]

  // 雾面透明度
  const fogOpacity = scrollProgress * (0.5 + Math.abs(mouse.y) * 0.5)

  // 点击卡片切换到对应底片
  const handleCardClick = (cardImg: string) => {
    const idx = BACKGROUNDS.indexOf(cardImg)
    if (idx !== -1) {
      setSlide(idx)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }

  return (
    <section
      id="section-home"
      ref={containerRef}
      className="hero-section"
      onMouseMove={handleMouseMove}
    >
      {/* 背景图层 */}
      {BACKGROUNDS.map((bg, i) => (
        <div
          key={bg}
          className={`hero-bg ${i === slide ? 'active' : ''}`}
          style={{
            backgroundImage: `url(${bg})`,
            transform: `scale(1.08) translate(${mouse.x * PARALLAX_INTENSITY * 0.3}px, ${mouse.y * PARALLAX_INTENSITY * 0.3}px)`,
          }}
        />
      ))}

      {/* 暗色遮罩 - 更强，让背景只是点缀 */}
      <div className="hero-overlay" />

      {/* 噪点纹理层 */}
      <div className="hero-noise" />

      {/* 主内容 - 错位排版 */}
      <div className="hero-content">
        {/* 左侧文字区 - 错位布局 */}
        <div className="hero-text-area">
          {/* 地点标签 - 最上方，小字 */}
          <div className={`hero-location-wrap ${isAnimating ? 'animate-in' : ''}`} style={{ animationDelay: '0ms' }}>
            <span className="hero-location-dot" />
            <span className="hero-location">{q.location}</span>
          </div>

          {/* 主标题 - 超大书法字，偏左 */}
          <h1 className={`hero-title-main ${isAnimating ? 'animate-in-left' : ''}`} style={{ animationDelay: '100ms' }}>
            {q.title}
          </h1>

          {/* 分隔线 - 短而精致 */}
          <div className={`hero-divider ${isAnimating ? 'animate-in' : ''}`} style={{ animationDelay: '200ms' }} />

          {/* 副标题 - 中等大小，偏右错位 */}
          <h2 className={`hero-title-sub ${isAnimating ? 'animate-in-right' : ''}`} style={{ animationDelay: '300ms' }}>
            {q.subtitle}
          </h2>

          {/* 引用文案 - 小字，居中偏左 */}
          <p className={`hero-quote ${isAnimating ? 'animate-in' : ''}`} style={{ animationDelay: '400ms' }}>
            {q.quote}
          </p>

          {/* CTA 按钮 - 偏左下 */}
          <div className={`hero-cta-wrapper ${isAnimating ? 'animate-in-left' : ''}`} style={{ animationDelay: '500ms' }}>
            <GlassButton onClick={onExplore} className="hero-cta">
              旅游攻略
              <span className="hero-cta-arrow">→</span>
            </GlassButton>
          </div>
        </div>

        {/* 右侧目的地卡片 - 随背景切换 */}
        <div className={`hero-dest-cards ${isAnimating ? 'animate-in-right' : ''}`} style={{ animationDelay: '600ms' }} key={`cards-${slide}`}>
          {q.cards.map((card, i) => (
            <div
              key={`${card.name}-${slide}`}
              className="dest-card animate-in"
              onClick={() => handleCardClick(card.img)}
              style={{
                transform: `translate(${mouse.x * PARALLAX_INTENSITY * 0.5 * (i + 1) * 0.3}px, ${mouse.y * PARALLAX_INTENSITY * 0.5 * (i + 1) * 0.3}px)`,
                animationDelay: `${700 + i * 150}ms`,
              }}
            >
              <div className="dest-card-img" style={{ backgroundImage: `url(${card.img})` }} />
              <div className="dest-card-overlay" />
              <div className="dest-card-info">
                <span className="dest-card-name">{card.name}</span>
                <span className="dest-card-stars">
                  {'★'.repeat(card.rating)}
                  <span className="dest-card-stars-empty">{'★'.repeat(5 - card.rating)}</span>
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 底部页码指示 */}
      <div className="hero-dots">
        {BACKGROUNDS.map((_, i) => (
          <button
            key={i}
            className={`hero-dot ${i === slide ? 'active' : ''}`}
            onClick={() => { setSlide(i); if (timerRef.current) clearInterval(timerRef.current) }}
          />
        ))}
      </div>

      {/* 底部动态雾面过渡 */}
      <div
        className="hero-fog-transition"
        style={{
          opacity: fogOpacity,
        }}
      />
    </section>
  )
}
