/**
 * 灵感漫游对话页 — InspireChatPage
 * SSE 流式输出 + LangGraph 图驱动
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SimpleHeader from '../components/SimpleHeader'
import { saveCacheRecord } from '../utils/cache'

const SESSION_KEY = 'travel_inspire_session_id'
const PROGRESS_KEY = 'travel_inspire_progress'
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

interface CityCard {
  city: string
  score: number
  reason: string
  tags: string[]
  daily_cost: number
  intro: string
  image_url: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  cities?: CityCard[]
  quickActions?: string[]
  timestamp: Date
}

export default function InspireChatPage() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string>('')
  const [userInfo, setUserInfo] = useState<Record<string, any>>({})
  const [streamText, setStreamText] = useState('')
  const [streamCities, setStreamCities] = useState<CityCard[] | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const sidRef = useRef<string>('')
  const initializedRef = useRef(false)  // 防止 React 18 严格模式双重执行

  useEffect(() => { sidRef.current = sessionId }, [sessionId])

  // 初始化：始终新对话（用 ref 防止 React 18 严格模式双重执行）
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    localStorage.removeItem(SESSION_KEY)
    localStorage.removeItem(PROGRESS_KEY)
    streamChat('')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamText])

  const saveProgress = (sid: string, phase: string) => {
    localStorage.setItem(SESSION_KEY, sid)
    localStorage.setItem(PROGRESS_KEY, JSON.stringify({
      session_id: sid, phase, updated_at: Date.now(),
    }))
  }

  /** SSE 流式对话核心 */
  const streamChat = useCallback(async (message: string) => {
    setLoading(true)
    setStreamText('')
    setStreamCities(null)

    let accumulated = ''
    let quickActions: string[] = []
    let citiesData: CityCard[] | null = null
    let finalPhase = ''

    try {
      const res = await fetch(`${API_BASE}/api/inspire/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: sidRef.current || undefined }),
      })

      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue
          let event = '', data = ''
          for (const line of part.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7)
            else if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!event || !data) continue

          try {
            const parsed = JSON.parse(data)
            switch (event) {
              case 'session':
                setSessionId(parsed.session_id)
                break
              case 'text_chunk':
                accumulated += parsed.content
                setStreamText(accumulated)
                break
              case 'cities':
                citiesData = parsed.cities
                setStreamCities(parsed.cities)
                break
              case 'quick_actions':
                quickActions = parsed.actions
                break
              case 'done':
                finalPhase = parsed.phase
                break
            }
          } catch { /* skip */ }
        }
      }

      if (accumulated || citiesData) {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: accumulated,
          cities: citiesData || undefined,
          quickActions: quickActions.length > 0 ? quickActions : undefined,
          timestamp: new Date(),
        }
        setMessages(prev => [...prev, assistantMsg])
        if (finalPhase) saveProgress(sidRef.current, finalPhase)
      }
    } catch (e) {
      console.error('流式请求失败:', e)
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，网络好像出了点问题，请重试～',
        timestamp: new Date(),
      }])
    } finally {
      setStreamText('')
      setStreamCities(null)
      setLoading(false)
      inputRef.current?.focus()
    }
  }, [])

  const sendMessage = (text: string) => {
    if (loading) return
    if (!text && messages.length === 0) {
      streamChat('')
      return
    }
    if (!text.trim()) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    streamChat(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const handleQuickAction = (action: string) => {
    sendMessage(action)
  }

  // 选城市：存历史 + 存进度 + 跳转
  const handleCityClick = (city: string) => {
    const formData = {
      origin: userInfo.origin || '',
      budget: userInfo.budget || 5000,
      companions: userInfo.companions || 2,
      days: userInfo.days || 3,
      intensity: userInfo.intensity || '莫名其妙地玩',
      preferences: userInfo.preferences || [],
    }
    sessionStorage.setItem('travel_form_data', JSON.stringify(formData))
    sessionStorage.setItem('travel_selected_city', city)

    // ⭐ 写入首页"旅行者"历史
    const lastCitiesMsg = [...messages].reverse().find(m => m.cities && m.cities.length > 0)
    try {
      saveCacheRecord({
        destination: city,
        origin: formData.origin,
        budgetMin: formData.budget,
        budgetMax: formData.budget,
        days: formData.days,
        pace: formData.intensity,
        companions: String(formData.companions),
        companionCount: formData.companions,
        preferences: formData.preferences,
        customPreference: '',
        age: 0,
        cities: (lastCitiesMsg?.cities || []).map(c => ({
          city: c.city,
          score: c.score,
          reason: c.reason,
          image: c.image_url,
        })),
      })
    } catch (e) {
      console.warn('保存历史记录失败:', e)
    }

    if (sessionId) {
      localStorage.setItem(SESSION_KEY, sessionId)
      localStorage.setItem(PROGRESS_KEY, JSON.stringify({
        session_id: sessionId,
        phase: 'generating_itinerary',
        selected_city: city,
        updated_at: Date.now(),
      }))
    }

    navigate(`/workshop/${encodeURIComponent(city)}`)
  }

  const handleNewChat = () => {
    localStorage.removeItem(SESSION_KEY)
    localStorage.removeItem(PROGRESS_KEY)
    sessionStorage.removeItem('travel_form_data')
    sessionStorage.removeItem('travel_selected_city')
    setMessages([])
    setSessionId('')
    setUserInfo({})
    streamChat('')
  }

  // P8: 用户反馈 — 点赞/踩某个 POI
  const handleFeedback = async (poiName: string, feedback: 'liked' | 'disliked') => {
    if (!sidRef.current) return
    try {
      await fetch(`${API_BASE}/api/inspire/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sidRef.current,
          poi_name: poiName,
          city: userInfo.selected_city || '',
          feedback,
        }),
      })
    } catch (e) {
      console.warn('反馈提交失败', e)
    }
  }

  return (
    <>
      <SimpleHeader title="灵感漫游" />
      <div className="inspire-chat-page">
        <div style={{ textAlign: 'right', padding: '6px 20px 0' }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleNewChat}
            style={{ fontSize: 12 }}
          >
            + 新对话
          </button>
        </div>

        <div className="chat-messages">
          {messages.map(msg => (
            <div key={msg.id} className={`chat-message ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'assistant' ? '🌟' : '👤'}
              </div>
              <div className="message-content">
                <div className="message-text">
                  {msg.content.split('\n').map((line, i) => (
                    <p key={i}>{line || '\u00A0'}</p>
                  ))}
                </div>

                {msg.cities && msg.cities.length > 0 && (
                  <div className="city-cards-inline">
                    {msg.cities.map(city => (
                      <div
                        key={city.city}
                        className="city-card-mini"
                        onClick={() => handleCityClick(city.city)}
                      >
                        <img
                          className="city-card-img-mini"
                          src={city.image_url || '/assets/city/placeholder.svg'}
                          alt={city.city}
                          loading="lazy"
                          onError={(e) => { (e.target as HTMLImageElement).src = '/assets/city/placeholder.svg' }}
                        />
                        <div className="city-card-header">
                          <span className="city-name">{city.city}</span>
                          <span className="city-score">⭐ {city.score}</span>
                        </div>
                        <div className="city-card-intro">{city.intro || city.reason}</div>
                        <div className="city-card-tags">
                          {city.tags.slice(0, 3).map(tag => (
                            <span key={tag} className="city-tag">{tag}</span>
                          ))}
                        </div>
                        <div className="city-card-footer">
                          <span className="city-cost">¥{city.daily_cost}/天</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {msg.quickActions && msg.quickActions.length > 0 && (
                  <div className="quick-actions">
                    {msg.quickActions.map(action => (
                      <button
                        key={action}
                        className="quick-action-btn"
                        onClick={() => handleQuickAction(action)}
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* 流式输出中 */}
          {loading && (
            <div className="chat-message assistant loading">
              <div className="message-avatar">🌟</div>
              <div className="message-content">
                {streamCities && streamCities.length > 0 && (
                  <div className="city-cards-inline">
                    {streamCities.map(city => (
                      <div key={city.city} className="city-card-mini" onClick={() => handleCityClick(city.city)}>
                        <img className="city-card-img-mini" src={city.image_url || '/assets/city/placeholder.svg'} alt={city.city} loading="lazy"
                          onError={(e) => { (e.target as HTMLImageElement).src = '/assets/city/placeholder.svg' }} />
                        <div className="city-card-header">
                          <span className="city-name">{city.city}</span>
                          <span className="city-score">⭐ {city.score}</span>
                        </div>
                        <div className="city-card-intro">{city.intro || city.reason}</div>
                        <div className="city-card-tags">
                          {city.tags.slice(0, 3).map(tag => <span key={tag} className="city-tag">{tag}</span>)}
                        </div>
                        <div className="city-card-footer">
                          <span className="city-cost">¥{city.daily_cost}/天</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {streamText ? (
                  <div className="message-text">
                    {streamText.split('\n').map((line, i) => (
                      <p key={i}>{line || '\u00A0'}</p>
                    ))}
                  </div>
                ) : (
                  <div className="typing-indicator">
                    <span></span><span></span><span></span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input-area">
          <input
            ref={inputRef}
            type="text"
            className="chat-input"
            placeholder="告诉我你的想法..."
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          <button
            className="chat-send-btn"
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
          >
            发送
          </button>
        </div>
      </div>
    </>
  )
}