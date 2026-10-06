import { useState, useEffect, useCallback, useRef } from 'react'

const slides = [
  { img: '/backgrounds/bg-01.jpg', location: '北京 · 祈年殿',   quote: '等风来，不如追风去。' },
  { img: '/backgrounds/bg-02.jpg', location: '龙门 · 石窟',     quote: '山高路远，看世界 也找自己。' },
  { img: '/backgrounds/bg-03.jpg', location: '张掖 · 丹霞',     quote: '旅行是对平淡生活的一次越狱。' },
  { img: '/backgrounds/bg-04.jpg', location: '九寨 · 彩林',     quote: '风吹又日晒，自由又自在。' },
  { img: '/backgrounds/bg-05.png', location: '九寨 · 海子',     quote: '生活不是为了赶路，而是为了感受路。' },
  { img: '/backgrounds/bg-06.jpg', location: '雪乡 · 漠河',     quote: '山不见我，我自去见山。' },
  { img: '/backgrounds/bg-07.jpg', location: '北京 · 十七孔桥', quote: '出发永远比向往更有意义。' },
  { img: '/backgrounds/bg-08.jpg', location: '新疆 · 雪山',     quote: '答案都在路上 自由都在风里。' },
  { img: '/backgrounds/bg-09.jpg', location: '肇兴 · 寨',     quote: '那些要去的地方，都是素未谋面的故乡。' },
]

const TOTAL = slides.length

function preload(src: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve()
    img.onerror = () => resolve()
    img.src = src
  })
}

interface Props { onStart: () => void }

export default function Landing({ onStart }: Props) {
  const [index, setIndex] = useState(0)
  const [bgLayer, setBgLayer] = useState(0)
  const [bgSrc, setBgSrc] = useState<[string, string]>([slides[0].img, ''])
  const [textVisible, setTextVisible] = useState(true)
  const [cardVisible, setCardVisible] = useState(true)
  const transitioning = useRef(false)
  const slide = slides[index]

  const goTo = useCallback((next: number) => {
    if (transitioning.current) return
    transitioning.current = true
    const wrapped = ((next % TOTAL) + TOTAL) % TOTAL
    const nextImg = slides[wrapped].img
    const otherLayer = 1 - bgLayer

    setTextVisible(false)
    setCardVisible(false)

    preload(nextImg).then(() => {
      setBgSrc(prev => { const c = [...prev] as [string, string]; c[otherLayer] = nextImg; return c })
      requestAnimationFrame(() => {
        setBgLayer(otherLayer)
        setIndex(wrapped)
        setTimeout(() => { setTextVisible(true); setCardVisible(true) }, 500)
        setTimeout(() => { transitioning.current = false }, 1200)
      })
    })
  }, [bgLayer])

  const next = useCallback(() => goTo(index + 1), [index, goTo])
  const prev = useCallback(() => goTo(index - 1), [index, goTo])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') next()
      if (e.key === 'ArrowLeft') prev()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [next, prev])

  useEffect(() => {
    const id = setInterval(next, 7000)
    return () => clearInterval(id)
  }, [next])

  const [parallax, setParallax] = useState({ x: 0, y: 0 })
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      setParallax({
        x: (e.clientX / window.innerWidth - 0.5) * 12,
        y: (e.clientY / window.innerHeight - 0.5) * 12,
      })
    }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  const nextSlide = slides[(index + 1) % TOTAL]
  const nextNextSlide = slides[(index + 2) % TOTAL]

  return (
    <div className="slideshow">
      {/* 背景层 — contain 模式，不缩放裁剪 */}
      <div className={`bg-layer bg-a ${bgLayer === 0 ? 'active' : ''}`}
        style={{ backgroundImage: `url(${bgSrc[0]})`, transform: `translate(${parallax.x * 0.3}px, ${parallax.y * 0.3}px)` }} />
      <div className={`bg-layer bg-b ${bgLayer === 1 ? 'active' : ''}`}
        style={{ backgroundImage: `url(${bgSrc[1]})`, transform: `translate(${parallax.x * 0.3}px, ${parallax.y * 0.3}px)` }} />
      <div className="bg-overlay" />

      {/* 顶部导航 */}
      <nav className="top-nav">
        <div className="nav-logo">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
          </svg>
          <span>Travel Agent</span>
        </div>
        <ul className="nav-links">
          <li className="active">首页</li><li>目的地</li><li>博客</li><li>关于</li>
        </ul>
        <div className="nav-user">
          <div className="avatar" /><span>旅行者</span>
        </div>
      </nav>

      {/* 左侧时间线 */}
      <div className="timeline">
        {slides.map((_, i) => (
          <div key={i} className={`timeline-dot ${i === index ? 'active' : ''} ${i < index ? 'past' : ''}`} onClick={() => goTo(i)} />
        ))}
      </div>

      {/* 主内容 */}
      <div className="main-content">
        <div className={`text-area ${textVisible ? 'visible' : 'hidden'}`}>
          <p className="location-label">{slide.location}</p>
          <h1 className="hero-title">
            <span className="title-line">探索</span>
            <span className="title-line accent">无界之旅</span>
          </h1>
          <p className="hero-quote">"{slide.quote}"</p>
          <button className="explore-btn" onClick={onStart}>
            旅游攻略
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <div className={`cards-area ${cardVisible ? 'visible' : 'hidden'}`}>
          <div className="dest-card large" onClick={() => goTo((index + 1) % TOTAL)}>
            <div className="card-img" style={{ backgroundImage: `url(${nextSlide.img})` }} />
            <div className="card-info">
              <span className="card-location">{nextSlide.location}</span>
              <div className="card-stars">{'★'.repeat(5)}</div>
            </div>
          </div>
          <div className="dest-card small" onClick={() => goTo((index + 2) % TOTAL)}>
            <div className="card-img" style={{ backgroundImage: `url(${nextNextSlide.img})` }} />
            <div className="card-info">
              <span className="card-location">{nextNextSlide.location}</span>
              <div className="card-stars">{'★'.repeat(5)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* 底部控制 */}
      <div className="bottom-controls">
        <div className="slide-counter">
          <span className="current-num">{String(index + 1).padStart(2, '0')}</span>
          <span className="divider">/</span>
          <span className="total-num">{String(TOTAL).padStart(2, '0')}</span>
        </div>
        <div className="dots">
          {slides.map((_, i) => (
            <button key={i} className={`dot ${i === index ? 'active' : ''}`} onClick={() => goTo(i)} aria-label={`第${i + 1}张`} />
          ))}
        </div>
        <div className="nav-arrows">
          <button className="arrow-btn" onClick={prev} aria-label="上一张">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
          </button>
          <button className="arrow-btn" onClick={next} aria-label="下一张">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
          </button>
        </div>
      </div>
    </div>
  )
}
