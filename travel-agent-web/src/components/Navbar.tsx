/**
 * 顶部导航栏
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getCacheRecords, deleteCacheRecord, type TravelCacheRecord } from '../utils/cache'

const SCROLL_OFFSET = 100
const NAV_HEIGHT = 72

type NavPage = 'home' | 'intro' | 'about'

interface NavProps {
  currentPage: NavPage
  onNavigate: (page: NavPage) => void
}

const NAV_ITEMS: { id: NavPage; label: string }[] = [
  { id: 'home', label: '首页' },
  { id: 'intro', label: '介绍' },
  { id: 'about', label: '关于' },
]

export default function Navbar({ currentPage, onNavigate }: NavProps) {
  const [scrolled, setScrolled] = useState(false)
  const [showCacheMenu, setShowCacheMenu] = useState(false)
  const [cacheRecords, setCacheRecords] = useState<TravelCacheRecord[]>([])
  const menuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    setCacheRecords(getCacheRecords())
  }, [showCacheMenu])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowCacheMenu(false)
      }
    }
    if (showCacheMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showCacheMenu])

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > NAV_HEIGHT)

      if (window.scrollY < SCROLL_OFFSET) {
        if (currentPage !== 'home') onNavigate('home')
      } else {
        const introEl = document.getElementById('section-intro')
        const aboutEl = document.getElementById('section-about')

        if (aboutEl && window.scrollY >= aboutEl.offsetTop - 300) {
          if (currentPage !== 'about') onNavigate('about')
        } else if (introEl && window.scrollY >= introEl.offsetTop - 300) {
          if (currentPage !== 'intro') onNavigate('intro')
        } else {
          if (currentPage !== 'home') onNavigate('home')
        }
      }
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [currentPage, onNavigate])

  const scrollToSection = (page: NavPage) => {
    onNavigate(page)
    const el = document.getElementById(
      page === 'home' ? 'section-home' : page === 'intro' ? 'section-intro' : 'section-about'
    )
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    } else if (page === 'home') {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  // ⭐ 点击历史记录 → 恢复工作台
  const handleCacheClick = (record: TravelCacheRecord) => {
    setShowCacheMenu(false)

    const formData = {
      origin: record.origin || '',
      budget: record.budgetMax || 5000,
      companions: record.companionCount || 2,
      days: record.days || 3,
      intensity: record.pace || '莫名其妙地玩',
      preferences: record.preferences || [],
    }
    sessionStorage.setItem('travel_form_data', JSON.stringify(formData))
    sessionStorage.setItem('travel_selected_city', record.destination)

    navigate(`/workshop/${encodeURIComponent(record.destination)}`)
  }

  const handleDeleteCache = (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    deleteCacheRecord(id)
    setCacheRecords(getCacheRecords())
  }

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    const days = Math.floor(diff / 86400000)

    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes}分钟前`
    if (hours < 24) return `${hours}小时前`
    if (days < 7) return `${days}天前`
    return date.toLocaleDateString('zh-CN')
  }

  return (
    <nav className={`site-nav ${scrolled ? 'scrolled' : ''}`}>
      <div className="nav-logo">
        <span className="nav-logo-icon">✦</span>
        <span className="nav-logo-text">Travel Agent</span>
      </div>
      <div className="nav-links">
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            className={`nav-link ${currentPage === item.id ? 'active' : ''}`}
            onClick={() => scrollToSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="nav-user" ref={menuRef}>
        <button
          className="nav-user-btn"
          onClick={() => setShowCacheMenu(!showCacheMenu)}
        >
          <span className="nav-user-avatar">🌏</span>
          <span className="nav-user-label">旅行者</span>
          {cacheRecords.length > 0 && (
            <span className="nav-cache-badge">{cacheRecords.length}</span>
          )}
        </button>

        {showCacheMenu && (
          <div className="cache-dropdown">
            <div className="cache-dropdown-header">
              <span>📝 搜索记录</span>
              {cacheRecords.length > 0 && (
                <span className="cache-count">{cacheRecords.length} 条</span>
              )}
            </div>
            <div className="cache-dropdown-list">
              {cacheRecords.length === 0 ? (
                <div className="cache-empty">暂无搜索记录</div>
              ) : (
                cacheRecords.map(record => (
                  <div
                    key={record.id}
                    className="cache-item"
                    onClick={() => handleCacheClick(record)}
                  >
                    <div className="cache-item-main">
                      <span className="cache-item-destination">{record.destination}</span>
                      <span className="cache-item-time">{formatTime(record.timestamp)}</span>
                    </div>
                    <div className="cache-item-details">
                      {record.origin} · {record.days}天 · ¥{record.budgetMin}-{record.budgetMax}
                    </div>
                    <button
                      className="cache-item-delete"
                      onClick={(e) => handleDeleteCache(e, record.id)}
                      title="删除"
                    >
                      ×
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </nav>
  )
}