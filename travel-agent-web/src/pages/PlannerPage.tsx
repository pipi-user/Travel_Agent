/**
 * 行程规划页面
 * 左侧 POI 卡片池 + 右侧行程编辑器 + 地图
 */

import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  DndContext,
  DragOverlay,
  closestCorners,
  useSensor,
  useSensors,
  PointerSensor,
  useDraggable,
  useDroppable,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core'
import { fetchPOIs, type POIItem, type POIResponse } from '../api/explore'
import { fetchTargetPlan, type TargetPlanResponse } from '../api/target'
import { arrangeItinerary } from '../api/planner'
import AmapView from '../components/AmapView'
import './PlannerPage.css'

/* ============ 可拖拽 POI 卡片 ============ */
function DraggablePOICard({ poi, children }: { poi: POIItem; children: React.ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: poi.id })
  return (
    <div
      ref={setNodeRef}
      className={`poi-card ${isDragging ? 'dragging' : ''}`}
      {...listeners}
      {...attributes}
    >
      {children}
    </div>
  )
}

/* ============ 可放置时段区域 ============ */
function DroppablePeriod({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div ref={setNodeRef} className={`period-block ${isOver ? 'period-over' : ''}`}>
      <span className="period-label">{label}</span>
      <div className="period-items">{children}</div>
    </div>
  )
}

interface DaySchedule {
  day: number
  morning: POIItem[]
  afternoon: POIItem[]
  evening: POIItem[]
}

export default function PlannerPage() {
  const { city } = useParams<{ city: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as any

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [poiPool, setPoiPool] = useState<POIItem[]>([])
  const [schedule, setSchedule] = useState<DaySchedule[]>([])
  const [activePOI, setActivePOI] = useState<POIItem | null>(null)
  const [itinerary, setItinerary] = useState<any>(null)
  const [showItinerary, setShowItinerary] = useState(false)

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

  // 加载 POI 数据
  useEffect(() => {
    if (!city) return
    const loadData = async () => {
      setLoading(true)
      try {
        // 确保天数有效（1-30天）
        const days = Math.max(1, Math.min(30, state?.days || 3))
        
        let response: POIResponse | TargetPlanResponse
        if (state?.mode === 'target') {
          response = await fetchTargetPlan({
            origin: state.origin || '未知',
            dest_city: city,
            days: days,
            pace: state.pace || '边走边躺',
            companions: state.companions || '独自',
            start_date: new Date().toISOString().split('T')[0],
            extra_notes: [
              ...(state.preferences || []),
              state.age ? `年龄：${state.age}岁` : '',
              state.budget ? `预算：¥${state.budget}` : '',
            ].filter(Boolean).join('；'),
          })
        } else {
          response = await fetchPOIs({
            city,
            preferences: state?.preferences || [],
            days: days,
            companions: state?.companions || '独自',
          })
        }
        
        // 根据实际天数初始化日程
        const initialSchedule: DaySchedule[] = Array.from({ length: days }, (_, i) => ({
          day: i + 1,
          morning: [],
          afternoon: [],
          evening: [],
        }))
        setSchedule(initialSchedule)

        // 合并所有 POI
        const allPOIs = [
          ...(response.attractions || []),
          ...(response.foods || []),
          ...(response.hotels || []),
        ]
        setPoiPool(allPOIs)
      } catch (err: any) {
        setError(err.message || '加载数据失败')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [city])

  // 拖拽开始
  const handleDragStart = (event: DragStartEvent) => {
    const poi = poiPool.find(p => p.id === event.active.id)
    setActivePOI(poi || null)
  }

  // 拖拽结束
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    setActivePOI(null)
    if (!over) return

    const poi = poiPool.find(p => p.id === active.id)
    if (!poi) return

    // 解析放置目标 (格式: "day1-morning")
    const overId = over.id as string
    const match = overId.match(/day(\d+)-(morning|afternoon|evening)/)
    if (!match) return

    const day = parseInt(match[1])
    const period = match[2] as 'morning' | 'afternoon' | 'evening'

    setSchedule(prev =>
      prev.map(s => {
        if (s.day !== day) return s
        // 检查是否已存在
        const exists = [...s.morning, ...s.afternoon, ...s.evening].some(p => p.id === poi.id)
        if (exists) return s
        return { ...s, [period]: [...s[period], poi] }
      })
    )
  }

  // 从日程中移除 POI
  const removeFromSchedule = (day: number, period: 'morning' | 'afternoon' | 'evening', poiId: string) => {
    setSchedule(prev =>
      prev.map(s => {
        if (s.day !== day) return s
        return { ...s, [period]: s[period].filter(p => p.id !== poiId) }
      })
    )
  }

  // 确认行程
  const handleConfirm = async () => {
    try {
      const days = schedule.map(s => ({
        day: s.day,
        items: [...s.morning, ...s.afternoon, ...s.evening].map(p => p.id),
      }))
      const result = await arrangeItinerary({
        city: city || '',
        days,
        poi_pool: poiPool,
        pace: '适中',
        request: state || {},
      })
      setItinerary(result.itinerary)
      setShowItinerary(true)
    } catch (err: any) {
      setError(err.message || '生成行程失败')
    }
  }

  // 生成外部搜索链接
  const getExternalLinks = (poi: POIItem) => ({
    baidu: `https://www.baidu.com/s?wd=${encodeURIComponent(poi.name + ' 旅游攻略')}`,
    xiaohongshu: `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(poi.name)}`,
    douyin: `https://www.douyin.com/search/${encodeURIComponent(poi.name + ' 旅游')}`,
  })

  // 收集已排入行程的 POI（用于地图显示）
  const scheduledPOIs = schedule.flatMap(day => [...day.morning, ...day.afternoon, ...day.evening])

  if (loading) {
    return (
      <div className="planner-page">
        <div className="loading-state">
          <div className="loading-spinner" />
          <p>正在加载 {city} 的推荐内容...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="planner-page">
      {/* 顶部栏 */}
      <div className="planner-header">
        <button className="back-btn" onClick={() => navigate(-1)}>← 返回</button>
        <h1 className="planner-title">{city} 行程规划</h1>
        <button className="confirm-btn" onClick={handleConfirm}>确认生成路线</button>
      </div>

      {error && <div className="error-msg">{error}</div>}

      <div className="planner-layout">
        <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          {/* 左侧 POI 卡片池 */}
          <div className="poi-pool-section">
            <h2 className="pool-title">可用景点 · 美食 · 酒店</h2>
            <div className="poi-grid">
              {poiPool.map(poi => (
                <DraggablePOICard key={poi.id} poi={poi}>
                  <div className="poi-card-header">
                    <span className={`poi-type-badge poi-type-${poi.type || 'attraction'}`}>
                      {poi.type === 'food' ? '美食' : poi.type === 'hotel' ? '酒店' : '景点'}
                    </span>
                    <span className="poi-rating">{'★'.repeat(Math.round((poi.rating || 5) / 2))}</span>
                  </div>
                  <h3 className="poi-name">{poi.name}</h3>
                  <p className="poi-desc">{poi.description || '暂无简介'}</p>
                  {poi.cost && <span className="poi-cost">¥{poi.cost}</span>}
                  {poi.duration && <span className="poi-duration">{poi.duration}</span>}
                  <div className="poi-links">
                    {Object.entries(getExternalLinks(poi)).map(([platform, url]) => (
                      <a key={platform} href={url} target="_blank" rel="noopener noreferrer" className="poi-link">
                        {platform === 'baidu' ? '百度' : platform === 'xiaohongshu' ? '小红书' : '抖音'}
                      </a>
                    ))}
                  </div>
                </DraggablePOICard>
              ))}
            </div>
            <DragOverlay>
              {activePOI ? (
                <div className="poi-card dragging">
                  <h3>{activePOI.name}</h3>
                </div>
              ) : null}
            </DragOverlay>

            {/* 地图区域 */}
            <AmapView pois={scheduledPOIs} />
          </div>

          {/* 右侧行程编辑器 */}
          <div className="schedule-section">
            <h2 className="schedule-title">我的行程</h2>
            {schedule.map(day => (
              <div key={day.day} className="day-block">
                <h3 className="day-label">Day {day.day}</h3>
                {(['morning', 'afternoon', 'evening'] as const).map(period => (
                  <DroppablePeriod
                    key={period}
                    id={`day${day.day}-${period}`}
                    label={period === 'morning' ? '上午' : period === 'afternoon' ? '下午' : '晚上'}
                  >
                    {day[period].map(poi => (
                      <div key={poi.id} className="scheduled-poi">
                        <span>{poi.name}</span>
                        <button className="remove-btn" onClick={() => removeFromSchedule(day.day, period, poi.id)}>×</button>
                      </div>
                    ))}
                    {day[period].length === 0 && (
                      <span className="period-empty">拖拽卡片到此处</span>
                    )}
                  </DroppablePeriod>
                ))}
              </div>
            ))}
          </div>
        </DndContext>
      </div>

      {/* 行程结果弹窗 */}
      {showItinerary && itinerary && (
        <div className="itinerary-modal">
          <div className="itinerary-content">
            <button className="close-modal" onClick={() => setShowItinerary(false)}>×</button>
            <h2>优化后的行程路线</h2>
            <pre className="itinerary-json">{JSON.stringify(itinerary, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
