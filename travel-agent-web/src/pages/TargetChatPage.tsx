/**
 * 定向定制对话页 — TargetChatPage
 *
 * Agent 驱动的需求采集 + 行程生成
 * SSE 流式输出 + 实时工具调用可视化
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SimpleHeader from '../components/SimpleHeader'

const SESSION_KEY = 'travel_target_session_id'
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

interface ItineraryDay {
  day: number
  items: ItineraryItem[]
  total_cost: number
}

interface ItineraryItem {
  poi_id: string
  period: string
  name: string
  poi_type: string
  cost: number
  duration: number
  lat: number
  lng: number
  image_url: string
}

interface ToolCall {
  tool: string
  summary: string
  result: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  quickActions?: string[]
  toolCalls?: ToolCall[]
  userInfo?: Record<string, any>
  timestamp: Date
}

// 信息收集进度字段
const INFO_FIELDS = [
  { key: 'dest_city', label: '目的地' },
  { key: 'origin', label: '出发地' },
  { key: 'days', label: '天数' },
  { key: 'companions', label: '人数' },
  { key: 'budget', label: '预算' },
]

/** 解析 SSE 文本流，提取 event + data */
function parseSSE(raw: string): { event: string; data: string }[] {
  const results: { event: string; data: string }[] = []
  const blocks = raw.split('\n\n')
  for (const block of blocks) {
    if (!block.trim()) continue
    let event = ''
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7)
      else if (line.startsWith('data: ')) data = line.slice(6)
    }
    if (event && data) results.push({ event, data })
  }
  return results
}

export default function TargetChatPage() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string>('')
  const [userInfo, setUserInfo] = useState<Record<string, any>>({})
  const [itinerary, setItinerary] = useState<ItineraryDay[] | null>(null)
  // 流式状态
  const [streamText, setStreamText] = useState('')
  const [streamTools, setStreamTools] = useState<ToolCall[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const sidRef = useRef<string>('')
  const initializedRef = useRef(false)  // 防止 React 18 严格模式双重执行

  // 同步 sessionId 到 ref
  useEffect(() => { sidRef.current = sessionId }, [sessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamText, streamTools])

  /** SSE 流式对话核心 */
  const streamChat = useCallback(async (message: string, sid?: string) => {
    setLoading(true)
    setStreamText('')
    setStreamTools([])

    let finalSid = sid || sidRef.current
    let accumulated = ''
    const tools: ToolCall[] = []
    let quickActions: string[] = []
    let finalPhase = ''
    let itineraryData: ItineraryDay[] | null = null

    try {
      const res = await fetch(`${API_BASE}/api/target/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: finalSid || undefined }),
      })

      if (!res.body) throw new Error('No response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 按双换行切分 SSE 事件
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
                finalSid = parsed.session_id
                setSessionId(parsed.session_id)
                localStorage.setItem(SESSION_KEY, parsed.session_id)
                break

              case 'text_chunk':
                accumulated += parsed.content
                setStreamText(accumulated)
                break

              case 'tool_call':
                tools.push({ tool: parsed.tool, summary: parsed.summary, result: '' })
                setStreamTools([...tools])
                break

              case 'tool_result': {
                const existing = tools.find(t => t.tool === parsed.tool)
                if (existing) existing.result = parsed.result
                setStreamTools([...tools])
                break
              }

              case 'quick_actions':
                quickActions = parsed.actions
                break

              case 'itinerary':
                itineraryData = parsed.itinerary
                setItinerary(parsed.itinerary)
                break

              case 'done':
                finalPhase = parsed.phase
                break
            }
          } catch {
            // JSON 解析失败，跳过
          }
        }
      }

      // 流结束，追加最终消息
      if (accumulated || tools.length > 0) {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: accumulated,
          quickActions: quickActions.length > 0 ? quickActions : undefined,
          toolCalls: tools.length > 0 ? tools : undefined,
          userInfo: userInfo,
          timestamp: new Date(),
        }
        setMessages(prev => [...prev, assistantMsg])
      }
    } catch (e) {
      console.error('流式请求失败:', e)
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，网络好像出了点问题，请重试～',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMsg])
    } finally {
      setStreamText('')
      setStreamTools([])
      setLoading(false)
      inputRef.current?.focus()
    }
  }, [userInfo])

  // 初始化：新对话触发问候（用 ref 防止 React 18 严格模式双重执行）
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    localStorage.removeItem(SESSION_KEY)
    streamChat('')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sendMessage = (text: string) => {
    if (loading) return
    if (!text.trim() && messages.length === 0) {
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

  const handleNewChat = () => {
    localStorage.removeItem(SESSION_KEY)
    setMessages([])
    setSessionId('')
    setUserInfo({})
    setItinerary(null)
    streamChat('')
  }

  // 跳转到工作台编辑行程
  const handleGoWorkshop = () => {
    const city = userInfo.dest_city
    if (!city) return
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
    navigate(`/workshop/${encodeURIComponent(city)}`)
  }

  // P3: 分享行程 — 生成文本摘要复制到剪贴板
  const handleShareItinerary = async () => {
    if (!itinerary || !userInfo.dest_city) return
    const periodMap: Record<string, string> = { morning: '早上', noon: '中午', afternoon: '下午', evening: '晚上' }
    let text = `🗺 ${userInfo.dest_city} ${userInfo.days}天行程\n`
    text += `💰 预算 ¥${userInfo.budget} | 👥 ${userInfo.companions}人\n\n`
    for (const day of itinerary) {
      text += `📅 第${day.day}天（¥${day.total_cost}）\n`
      for (const item of day.items) {
        const icon = item.poi_type === 'attraction' ? '🏛' : item.poi_type === 'food' ? '🍜' : '🏨'
        text += `  ${periodMap[item.period] || item.period}: ${icon} ${item.name || item.poi_id} ¥${item.cost}\n`
      }
      text += '\n'
    }
    text += '—— 来自 Travel Agent ✨'
    try {
      await navigator.clipboard.writeText(text)
      alert('行程已复制到剪贴板，快去分享吧～')
    } catch {
      // fallback: 创建 textarea 复制
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      alert('行程已复制到剪贴板～')
    }
  }

  // P8: 用户反馈 — 点赞/踩某个 POI
  const handleFeedback = async (poiName: string, feedback: 'liked' | 'disliked') => {
    if (!sidRef.current) return
    try {
      await fetch(`${API_BASE}/api/target/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sidRef.current,
          poi_name: poiName,
          city: userInfo.dest_city || '',
          feedback,
        }),
      })
    } catch (e) {
      console.warn('反馈提交失败', e)
    }
  }

  return (
    <>
      <SimpleHeader title="定向定制" />
      <div className="target-chat-page">
        <div style={{ textAlign: 'right', padding: '6px 20px 0' }}>
          <button className="btn btn-ghost btn-sm" onClick={handleNewChat} style={{ fontSize: 12 }}>
            + 新对话
          </button>
          {itinerary && (
            <>
              <button className="btn btn-primary btn-sm" onClick={handleGoWorkshop} style={{ fontSize: 12, marginLeft: 8 }}>
                编辑行程 →
              </button>
              <button className="btn btn-ghost btn-sm" onClick={handleShareItinerary} style={{ fontSize: 12, marginLeft: 8 }}>
                📤 分享
              </button>
            </>
          )}
        </div>

        {/* 信息收集进度 */}
        {Object.keys(userInfo).length > 0 && !itinerary && (
          <div className="info-progress" style={{ padding: '0 24px 8px' }}>
            {INFO_FIELDS.map(field => {
              const done = !!userInfo[field.key]
              return (
                <div key={field.key} className={`info-progress-item ${done ? 'done' : ''}`}>
                  {done && <span className="check">✓</span>}
                  {field.label}
                  {done && <span>: {userInfo[field.key]}</span>}
                </div>
              )
            })}
          </div>
        )}

        <div className="chat-messages">
          {messages.map(msg => (
            <div key={msg.id} className={`chat-message ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'assistant' ? '🎯' : '👤'}
              </div>
              <div className="message-content">
                <div className="message-text">
                  {msg.content.split('\n').map((line, i) => (
                    <p key={i}>{line || '\u00A0'}</p>
                  ))}
                </div>

                {/* Agent 工具调用展示 */}
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div>
                    {msg.toolCalls.map((tc, i) => (
                      <div key={i} className="tool-call-card">
                        <div className="tool-name">🔍 {tc.summary}</div>
                        <div className="tool-result">{tc.result}</div>
                      </div>
                    ))}
                  </div>
                )}

                {/* 行程预览 */}
                {msg.userInfo?.dest_city && itinerary && (
                  <div className="itinerary-preview">
                    <div className="itinerary-preview-title">
                      📋 {msg.userInfo.dest_city} {msg.userInfo.days}天行程
                    </div>
                    {itinerary.map(day => (
                      <div key={day.day} className="itinerary-preview-day">
                        <span className="day-label">Day {day.day}</span>
                        <span className="day-items">
                          {day.items.map((item, idx) => (
                            <span key={idx} className={`item-tag item-${item.poi_type}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                              {item.poi_type === 'attraction' ? '🏛' : item.poi_type === 'food' ? '🍜' : '🏨'}
                              {' '}{item.name || item.poi_id}
                              <span style={{ fontSize: 10, cursor: 'pointer', marginLeft: 2, opacity: 0.6 }}
                                onClick={() => handleFeedback(item.name || item.poi_id, 'liked')} title="喜欢">👍</span>
                              <span style={{ fontSize: 10, cursor: 'pointer', opacity: 0.6 }}
                                onClick={() => handleFeedback(item.name || item.poi_id, 'disliked')} title="不喜欢">👎</span>
                            </span>
                          ))}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {msg.quickActions && msg.quickActions.length > 0 && (
                  <div className="quick-actions">
                    {msg.quickActions.map(action => (
                      <button key={action} className="quick-action-btn" onClick={() => handleQuickAction(action)}>
                        {action}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* 流式输出中：实时展示文本 + 工具调用 */}
          {loading && (
            <div className="chat-message assistant loading">
              <div className="message-avatar">🎯</div>
              <div className="message-content">
                {/* 实时工具调用卡片 */}
                {streamTools.length > 0 && streamTools.map((tc, i) => (
                  <div key={i} className="tool-call-card">
                    <div className="tool-name">🔍 {tc.summary}</div>
                    {tc.result && <div className="tool-result">{tc.result}</div>}
                    {!tc.result && <div className="tool-result" style={{ opacity: 0.5 }}>执行中...</div>}
                  </div>
                ))}
                {/* 流式文本 */}
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
            placeholder="告诉我你的旅行需求..."
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
