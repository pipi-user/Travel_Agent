import { useState, useCallback } from 'react'
import { apiArrange, apiMarkLiked, apiMarkDisliked, apiMarkVisited, apiExtractMemories, DEMO_POIS, DEMO_ITINERARY } from '../api'
import type { POICard, TripRequest, DaySlot, ItineraryResult } from '../api'
import POICardView from './POICard'

interface Props {
  userId: string
  initialCity?: string
  initialPois?: { attractions: POICard[]; foods: POICard[]; hotels: POICard[] }
  initialRequest?: Partial<TripRequest>
  onMemoryExtracted: () => void
}

type ItineraryItem = { id: string; category: string; name: string; detail: string }
type DayData = { day: number; items: ItineraryItem[] }

export default function Planner({ userId, initialCity, initialPois, initialRequest, onMemoryExtracted }: Props) {
  const [phase, setPhase] = useState<'setup' | 'drag' | 'result'>('setup')
  const [loading, setLoading] = useState(false)

  // 设置
  const [city, setCity] = useState(initialCity || '')
  const [daysCount, setDaysCount] = useState(initialRequest?.days || 3)
  const [pace, setPace] = useState(initialRequest?.pace || '适中')
  const [selectedHotel, setSelectedHotel] = useState<POICard | null>(null)

  // POI 数据
  const [attractions, setAttractions] = useState<POICard[]>(initialPois?.attractions || DEMO_POIS.attractions)
  const [foods, setFoods] = useState<POICard[]>(initialPois?.foods || DEMO_POIS.foods)
  const [hotels, setHotels] = useState<POICard[]>(initialPois?.hotels || DEMO_POIS.hotels)
  const allPois = [...attractions, ...foods, ...hotels]

  // 拖拽状态
  const [pool, setPool] = useState<ItineraryItem[]>(() =>
    allPois.map(p => ({ id: p.id, category: p.type, name: p.name, detail: `${p.cost} · ${p.reason || p.description}` }))
  )
  const [days, setDays] = useState<DayData[]>(() =>
    Array.from({ length: daysCount }, (_, i) => ({ day: i + 1, items: [] }))
  )
  const [dragItem, setDragItem] = useState<ItineraryItem | null>(null)
  const [dragOverDay, setDragOverDay] = useState<number | null>(null)

  // 反馈状态
  const [likedIds, setLikedIds] = useState<Set<string>>(new Set())
  const [dislikedIds, setDislikedIds] = useState<Set<string>>(new Set())

  // 行程结果
  const [itinerary, setItinerary] = useState<ItineraryResult | null>(null)
  const [feedback, setFeedback] = useState('')
  const [extracted, setExtracted] = useState(0)

  // 拖拽
  const onDragStart = useCallback((item: ItineraryItem) => setDragItem(item), [])
  const onDragEnd = useCallback(() => { setDragItem(null); setDragOverDay(null) }, [])
  const onDayDragOver = useCallback((e: React.DragEvent, day: number) => { e.preventDefault(); setDragOverDay(day) }, [])
  const onDayDrop = useCallback((day: number) => {
    if (!dragItem) return
    setDays(prev => prev.map(d => d.day === day ? { ...d, items: [...d.items, dragItem] } : d))
    setPool(prev => prev.filter(p => p.id !== dragItem.id))
    setDragItem(null); setDragOverDay(null)
  }, [dragItem])
  const removeFromDay = useCallback((day: number, itemId: string) => {
    const item = days.find(d => d.day === day)?.items.find(i => i.id === itemId)
    if (item) {
      setDays(prev => prev.map(d => d.day === day ? { ...d, items: d.items.filter(i => i.id !== itemId) } : d))
      setPool(prev => [...prev, item])
    }
  }, [days])

  // 反馈操作
  const handleLike = async (poi: POICard) => {
    setLikedIds(prev => new Set(prev).add(poi.id))
    try { await apiMarkLiked(userId, poi.name, poi.city) } catch { /* ignore */ }
  }
  const handleDislike = async (poi: POICard) => {
    setDislikedIds(prev => new Set(prev).add(poi.id))
    try { await apiMarkDisliked(userId, poi.name, poi.city) } catch { /* ignore */ }
  }
  const handleVisit = async (poi: POICard) => {
    try { await apiMarkVisited(userId, poi.name, poi.city, new Date().toISOString().slice(0, 10)) } catch { /* ignore */ }
  }

  // 生成行程
  const handleGenerate = async () => {
    setLoading(true)
    const daySlots: DaySlot[] = days.map(d => ({ day: d.day, items: d.items.map(i => i.id) }))
    try {
      const res = await apiArrange({
        user_id: userId,
        request: { ...initialRequest, dest_city: city } as Partial<TripRequest>,
        city, days: daySlots, poi_pool: allPois, hotel: selectedHotel, pace,
      })
      setItinerary(res.itinerary)
    } catch {
      setItinerary(DEMO_ITINERARY)
    }
    setPhase('result'); setLoading(false)
  }

  // 记忆沉淀
  const handleExtract = async () => {
    if (!itinerary) return
    setLoading(true)
    try {
      const res = await apiExtractMemories(userId, itinerary as unknown as Record<string, unknown>, feedback)
      setExtracted(res.extracted)
    } catch { setExtracted(0) }
    setLoading(false)
    onMemoryExtracted()
  }

  const catIcon = (c: string) => c === 'attraction' ? '🏛️' : c === 'food' ? '🍜' : c === 'accommodation' || c === 'hotel' ? '🏨' : ''
  const catColor = (c: string) => c === 'attraction' ? '#4a90d9' : c === 'food' ? '#e08030' : c === 'accommodation' || c === 'hotel' ? '#2ecc71' : '#9b59b6'

  return (
    <div className="page planner-page">
      {/* Phase 1: 设置 */}
      {phase === 'setup' && (
        <div className="planner-setup fade-in">
          <h2 className="page-title">行程设置</h2>
          <div className="setup-grid">
            <div className="form-group">
              <label>目的地城市</label>
              <input value={city} onChange={e => setCity(e.target.value)} placeholder="如：北京" />
            </div>
            <div className="form-group">
              <label>天数</label>
              <input type="number" min={1} max={15} value={daysCount} onChange={e => {
                const n = +e.target.value; setDaysCount(n)
                setDays(Array.from({ length: n }, (_, i) => ({ day: i + 1, items: [] })))
              }} />
            </div>
            <div className="form-group">
              <label>节奏</label>
              <div className="seg-group">
                {['轻松', '适中', '紧凑'].map(p => (
                  <button key={p} className={`seg-btn ${pace === p ? 'active' : ''}`} onClick={() => setPace(p)}>{p}</button>
                ))}
              </div>
            </div>
          </div>

          {/* 酒店选择 */}
          <div className="hotel-select">
            <h3 className="section-title">选择住宿</h3>
            <div className="hotel-options">
              {hotels.map(h => (
                <button key={h.id} className={`hotel-option ${selectedHotel?.id === h.id ? 'active' : ''}`} onClick={() => setSelectedHotel(h)}>
                  <span>🏨</span>
                  <div><strong>{h.name}</strong><span>{h.cost} · {h.reason}</span></div>
                </button>
              ))}
            </div>
          </div>

          <button className="primary-btn" onClick={() => setPhase('drag')} disabled={!city.trim()}>
            开始拖拽规划
          </button>
        </div>
      )}

      {/* Phase 2: 拖拽 */}
      {phase === 'drag' && (
        <div className="planner-drag fade-in">
          <div className="drag-header">
            <h2 className="page-title" style={{ marginBottom: 0 }}>{city} · {daysCount}天行程</h2>
            <div className="drag-actions">
              <button className="secondary-btn" onClick={() => setPhase('setup')}>← 设置</button>
              <button className="primary-btn" onClick={handleGenerate} disabled={loading}>
                {loading ? '生成中...' : '生成行程'}
              </button>
            </div>
          </div>

          <div className="drag-layout">
            {/* 左侧：POI 池 */}
            <div className="drag-pool">
              <h3 className="pool-title">可用资源 <span className="pool-count">{pool.length}</span></h3>
              <p className="pool-hint">拖拽到右侧天数栏</p>
              <div className="pool-items">
                {pool.map(item => {
                  const poi = allPois.find(p => p.id === item.id)
                  return (
                    <div key={item.id} className="pool-card" draggable onDragStart={() => onDragStart(item)} onDragEnd={onDragEnd} style={{ borderLeftColor: catColor(item.category) }}>
                      <span className="pool-icon">{catIcon(item.category)}</span>
                      <div className="pool-info"><strong>{item.name}</strong><span>{item.detail}</span></div>
                      {poi && (
                        <div className="pool-quick-actions">
                          <button className={`quick-btn ${likedIds.has(poi.id) ? 'active' : ''}`} onClick={() => handleLike(poi)} title="喜欢">{likedIds.has(poi.id) ? '❤️' : ''}</button>
                          <button className={`quick-btn ${dislikedIds.has(poi.id) ? 'active' : ''}`} onClick={() => handleDislike(poi)} title="不喜欢">👎</button>
                        </div>
                      )}
                    </div>
                  )
                })}
                {pool.length === 0 && <p className="pool-empty">所有资源已安排 ✨</p>}
              </div>
            </div>

            {/* 右侧：天数槽 */}
            <div className="drag-days">
              <div className="days-grid">
                {days.map(slot => (
                  <div key={slot.day} className={`day-slot ${dragOverDay === slot.day ? 'drag-over' : ''}`} onDragOver={e => onDayDragOver(e, slot.day)} onDragLeave={() => setDragOverDay(null)} onDrop={() => onDayDrop(slot.day)}>
                    <div className="day-header">
                      <span className="day-badge">Day {slot.day}</span>
                      <span className="day-count">{slot.items.length} 项</span>
                    </div>
                    <div className="day-items">
                      {slot.items.map((item, idx) => (
                        <div key={item.id} className="day-card" style={{ borderLeftColor: catColor(item.category) }}>
                          <span className="day-order">{idx + 1}</span>
                          <span className="day-icon">{catIcon(item.category)}</span>
                          <div className="day-info"><strong>{item.name}</strong><span>{item.detail}</span></div>
                          <button className="day-remove" onClick={() => removeFromDay(slot.day, item.id)}>×</button>
                        </div>
                      ))}
                      {slot.items.length === 0 && <p className="day-empty">拖拽资源到此处</p>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Phase 3: 行程结果 + 记忆沉淀 */}
      {phase === 'result' && itinerary && (
        <div className="planner-result fade-in">
          <div className="result-header">
            <div>
              <h2 className="page-title">你的行程已生成</h2>
              {itinerary.summary && <p className="page-subtitle">{itinerary.summary}</p>}
            </div>
            <button className="secondary-btn" onClick={() => setPhase('drag')}>← 调整</button>
          </div>

          {/* 行程概览 */}
          <div className="result-overview">
            <div className="overview-stat"><span className="stat-num">{itinerary.days.length}</span><span className="stat-label">天</span></div>
            <div className="overview-stat"><span className="stat-num">{itinerary.days.reduce((s, d) => s + d.items.length, 0)}</span><span className="stat-label">个活动</span></div>
            <div className="overview-stat"><span className="stat-num">¥{itinerary.total_cost}</span><span className="stat-label">预估总费用</span></div>
          </div>

          {/* 每日行程 */}
          <div className="itinerary-days">
            {itinerary.days.map(day => (
              <div key={day.day} className="itinerary-day">
                <div className="day-head">
                  <span className="day-badge">Day {day.day}</span>
                  <span className="day-city">{day.city}</span>
                  <span className="day-intensity">{day.intensity}</span>
                </div>
                {day.hotel && <p className="day-hotel">🏨 {day.hotel}</p>}
                {day.transport_note && <p className="day-transport">{day.transport_note}</p>}
                <div className="day-timeline">
                  {day.items.map((item, idx) => (
                    <div key={idx} className="timeline-item">
                      <span className="timeline-time">{item.time}</span>
                      <div className="timeline-dot2" />
                      <div className="timeline-content">
                        <strong>{item.activity}</strong>
                        <span>{item.location} · {item.cost} · {item.duration_min}分钟</span>
                        {item.note && <span className="timeline-note">{item.note}</span>}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="day-cost">日费用: ¥{day.daily_cost}</p>
              </div>
            ))}
          </div>

          {itinerary.unscheduled.length > 0 && (
            <div className="unscheduled">
              <h4>未安排的 POI ({itinerary.unscheduled.length})</h4>
              <div className="unscheduled-list">
                {itinerary.unscheduled.map(id => {
                  const poi = allPois.find(p => p.id === id)
                  return poi ? <span key={id} className="unscheduled-tag">{poi.name}</span> : null
                })}
              </div>
            </div>
          )}

          {/* 记忆沉淀区 */}
          <div className="memory-section">
            <h3 className="section-title">记忆沉淀</h3>
            <p className="memory-hint">完成行程后，AI 将自动提取你的旅行偏好和记忆</p>
            <textarea
              className="feedback-input"
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              placeholder="这次旅行感觉如何？有什么想记住的？（选填）"
              rows={3}
            />
            <div className="memory-actions">
              <button className="primary-btn" onClick={handleExtract} disabled={loading}>
                {loading ? '提取中...' : extracted > 0 ? `已提取 ${extracted} 条记忆` : '提取记忆并保存'}
              </button>
            </div>
            {extracted > 0 && <p className="memory-success">已为你保存 {extracted} 条旅行记忆，去「记忆」页面查看吧！</p>}
          </div>
        </div>
      )}

      {loading && <div className="loading-overlay"><div className="spinner" /></div>}
    </div>
  )
}
