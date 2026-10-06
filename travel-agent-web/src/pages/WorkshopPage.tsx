/**
 * 拖拽自定义工作台 — WorkshopPage
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  DndContext, closestCorners, PointerSensor, useSensor, useSensors,
  useDraggable, useDroppable,
  type DragEndEvent,
} from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'

import SimpleHeader from '../components/SimpleHeader'
import AmapView from '../components/AmapView'
import POIDetailModal from '../components/POIDetailModal'
import {
  fetchPOIs, confirmRoute, adjustItinerary, replanItinerary,
  type POICard, type HotelPOI, type DaySchedule, type TimeSlotItem, type ExplorePoisResponse,
} from '../api/explore'
import { saveWorkshop, loadWorkshop } from '../utils/workshopStorage'

const POI_PLACEHOLDER = '/assets/poi/placeholder.svg'
const PERIODS = [
  { key: 'morning', label: '早', time: '06:00-11:00', icon: '🌅' },
  { key: 'noon', label: '中', time: '11:00-14:00', icon: '☀️' },
  { key: 'afternoon', label: '下午', time: '14:00-18:00', icon: '🌤' },
  { key: 'evening', label: '晚', time: '18:00-22:00', icon: '🌙' },
] as const

type TabFilter = 'all' | 'attraction' | 'food' | 'hotel'

export default function WorkshopPage() {
  const { city } = useParams<{ city: string }>()
  const navigate = useNavigate()
  const decodedCity = decodeURIComponent(city || '')

  const [pois, setPois] = useState<POICard[]>([])
  const [hotels, setHotels] = useState<HotelPOI[]>([])
  const [itinerary, setItinerary] = useState<DaySchedule[]>([])
  const [initialItinerary, setInitialItinerary] = useState<DaySchedule[]>([])
  const [selectedHotel, setSelectedHotel] = useState<HotelPOI | null>(null)
  const [originalHotel, setOriginalHotel] = useState<HotelPOI | null>(null)
  const [replanning, setReplanning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [activeTab, setActiveTab] = useState<TabFilter>('all')
  const [activeDay, setActiveDay] = useState(1)
  const [detailPoi, setDetailPoi] = useState<POICard | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [adjustInput, setAdjustInput] = useState('')
  const [adjusting, setAdjusting] = useState(false)
  const [adjustMsg, setAdjustMsg] = useState('')

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    if (!decodedCity) return

    const saved = loadWorkshop(decodedCity)
    if (saved && saved.pois && saved.pois.length > 0) {
      setPois(saved.pois)
      setHotels(saved.hotels || [])
      setItinerary(saved.itinerary || [])
      setInitialItinerary(saved.itinerary || [])
      setSelectedHotel(saved.selectedHotel)
      setLoading(false)
      return
    }

    const formData = sessionStorage.getItem('travel_form_data')
    if (!formData) {
      setError('缺少表单数据，请返回重新填写')
      setLoading(false)
      return
    }

    const form = JSON.parse(formData)
    setLoading(true)

    fetchPOIs({
      city: decodedCity,
      budget: form.budget,
      companions: form.companions,
      days: form.days,
      intensity: form.intensity,
      preferences: form.preferences || [],
    }).then((data: ExplorePoisResponse) => {
      setPois(data.pois)
      setHotels(data.hotels)
      setItinerary(data.initial_itinerary)
      setInitialItinerary(data.initial_itinerary)

      // ⭐ 自动选"离所有 POI 中心最近"的酒店
      let autoHotel = null
      if (data.hotels.length > 0 && data.pois.length > 0) {
        const validPois = data.pois.filter((p: any) => p.lat && p.lng)
        if (validPois.length > 0) {
          const cLat = validPois.reduce((s: number, p: any) => s + p.lat, 0) / validPois.length
          const cLng = validPois.reduce((s: number, p: any) => s + p.lng, 0) / validPois.length

          const candidates = data.hotels
            .filter((h: any) => h.lat && h.lng)
            .map((h: any) => ({
              hotel: h,
              dist: Math.sqrt((h.lat - cLat) ** 2 + (h.lng - cLng) ** 2),
            }))

          if (candidates.length > 0) {
            autoHotel = candidates.reduce((a: any, b: any) => (a.dist < b.dist ? a : b)).hotel
          }
        }
      }
      if (autoHotel) {
        setSelectedHotel(autoHotel)
        setOriginalHotel(autoHotel)
      }

      saveWorkshop(decodedCity, {
        pois: data.pois,
        hotels: data.hotels,
        itinerary: data.initial_itinerary,
        selectedHotel: autoHotel,
      })
    }).catch(e => {
      console.error(e)
      setError('获取 POI 数据失败')
    }).finally(() => setLoading(false))
  }, [decodedCity])

  const autoSave = useCallback(() => {
    if (!decodedCity) return
    if (loading) return
    if (pois.length === 0 && hotels.length === 0) return
    saveWorkshop(decodedCity, { itinerary, selectedHotel, pois, hotels })
  }, [decodedCity, itinerary, selectedHotel, pois, hotels, loading])

  useEffect(() => { autoSave() }, [autoSave])

  const poiMap = useMemo(() => {
    const map: Record<string, POICard> = {}
    pois.forEach(p => { map[p.id] = p })
    hotels.forEach(h => { map[h.id] = h })
    return map
  }, [pois, hotels])

  const filteredPois = useMemo(() => {
    if (activeTab === 'all') return pois
    return pois.filter(p => p.poi_type === activeTab)
  }, [pois, activeTab])

  const currentDaySchedule = useMemo(() => {
    return itinerary.find(d => d.day === activeDay) || { day: activeDay, items: [] as TimeSlotItem[] }
  }, [itinerary, activeDay])

  const getPeriodItems = useCallback((period: string) => {
    return currentDaySchedule.items.filter(item => item.period === period)
  }, [currentDaySchedule])

  const handleDragEnd = useCallback((e: DragEndEvent) => {
    setActiveId(null)
    const { active, over } = e
    if (!over) return

    const dragId = active.id as string
    const overId = over.id as string

    const periodMatch = overId.match(/^period-(morning|noon|afternoon|evening)$/)
    if (periodMatch) {
      const period = periodMatch[1] as TimeSlotItem['period']
      const poi = poiMap[dragId]
      if (!poi || poi.poi_type === 'hotel') return
      const alreadyIn = currentDaySchedule.items.some(item => item.poi_id === dragId)
      if (alreadyIn) return
      setItinerary(prev => prev.map(d => {
        if (d.day !== activeDay) return d
        return { ...d, items: [...d.items, { poi_id: dragId, period }] }
      }))
    }
  }, [poiMap, currentDaySchedule, activeDay])

  const removeFromSlot = useCallback((poiId: string) => {
    setItinerary(prev => prev.map(d => {
      if (d.day !== activeDay) return d
      return { ...d, items: d.items.filter(item => item.poi_id !== poiId) }
    }))
  }, [activeDay])

  const handleReset = useCallback(() => {
    if (initialItinerary.length > 0) {
      setItinerary(initialItinerary)
      setSelectedHotel(originalHotel)
    }
  }, [initialItinerary, originalHotel])

  const handleConfirm = useCallback(async () => {
    setConfirming(true)
    try {
      await confirmRoute({
        city: decodedCity,
        days: itinerary.length,
        slots: itinerary,
        hotel: selectedHotel,
        pois: [...pois, ...hotels],
      })
     sessionStorage.setItem('travel_route_city', decodedCity)
      navigate(`/route-result/${encodeURIComponent(decodedCity)}`)
    } catch (e) {
      console.error(e)
      alert('确认行程失败，请重试')
    } finally {
      setConfirming(false)
    }
  }, [decodedCity, itinerary, selectedHotel, pois, hotels, navigate])

  const handleHotelChange = useCallback((hotel: HotelPOI) => {
    if (selectedHotel?.id === hotel.id) {
      setSelectedHotel(null)
      return
    }
    setSelectedHotel(hotel)
    // 如果换酒店，自动弹出确认是否重新规划
    if (originalHotel && hotel.id !== originalHotel.id) {
      if (window.confirm(`已选择「${hotel.name}」，是否按此酒店重新规划行程？`)) {
        // 延迟执行，等 state 更新
        setTimeout(() => {
          handleReplanWithHotel(hotel)
        }, 100)
      }
    }
  }, [selectedHotel, originalHotel])

  const handleReplanWithHotel = useCallback(async (hotel?: HotelPOI) => {
    const targetHotel = hotel || selectedHotel
    if (!targetHotel || replanning) return
    setReplanning(true)
    try {
      const result = await replanItinerary({
        city: decodedCity,
        hotel_id: targetHotel.id,
        pois,
        hotels,
        days: itinerary.length,
      })
      setItinerary(result.itinerary)
      setInitialItinerary(result.itinerary)
      setOriginalHotel(targetHotel)
      alert('行程已重新规划！')
    } catch (e) {
      console.error(e)
      alert('重新规划失败，请重试')
    } finally {
      setReplanning(false)
    }
  }, [decodedCity, selectedHotel, pois, hotels, itinerary.length, replanning])

    const handleAdjust = useCallback(async () => {
    if (!adjustInput.trim() || adjusting) return
    setAdjusting(true)
    setAdjustMsg('')
    try {
      const result = await adjustItinerary({
        city: decodedCity,
        message: adjustInput,
        itinerary,
        pois: [...pois, ...hotels],
      })
      setItinerary(result.itinerary)
      setAdjustMsg(result.text)
      setAdjustInput('')
    } catch (e: any) {
      setAdjustMsg(`调整失败：${e.message}`)
    } finally {
      setAdjusting(false)
    }
  }, [adjustInput, adjusting, decodedCity, itinerary, pois, hotels])

    const mapPois = useMemo(() => {
    const items = currentDaySchedule.items
      .map(item => poiMap[item.poi_id])
      .filter(Boolean)
      .map(p => ({
        id: p.id,
        name: p.name,
        lat: p.lat,
        lng: p.lng,
        poi_type: p.poi_type,
      }))

    // ⭐ 加酒店（第 1 天显示）
    if (selectedHotel &&  (selectedHotel as any).lat && (selectedHotel as any).lng) {
      items.push({
        id: selectedHotel.id,
        name: `🏨 ${selectedHotel.name}`,
        lat: (selectedHotel as any).lat,
        lng: (selectedHotel as any).lng,
        poi_type: 'hotel',
      })
    }
    return items
  }, [currentDaySchedule, poiMap, selectedHotel, activeDay])

  if (loading) {
    return (
      <>
        <SimpleHeader title={decodedCity} />
        <div className="loading-overlay">
          <div className="loading-icon">️</div>
          <div className="loading-title">正在加载 {decodedCity} 的旅行资源...</div>
          <div className="loading-steps">
            <div className="loading-step done">✓ 搜索景点和餐厅</div>
            <div className="loading-step active"> 采集酒店和交通信息</div>
            <div className="loading-step">○ 生成最优行程</div>
          </div>
          <div className="loading-bar">
            <div className="loading-bar-fill" style={{ width: '40%' }} />
          </div>
        </div>
      </>
    )
  }

  if (error) {
    return (
      <>
        <SimpleHeader title={decodedCity} />
        <div className="empty-state" style={{ paddingTop: 100 }}>
          <div className="empty-icon">⚠️</div>
          <div className="empty-text">{error}</div>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/')}>
            返回表单
          </button>
        </div>
      </>
    )
  }

  return (
    <>
      <SimpleHeader title={decodedCity} />

      <div className="workshop-toolbar">
        <div className="toolbar-city">{decodedCity} 行程规划</div>
        <div className="toolbar-actions">
          <button className="btn btn-ghost btn-sm" onClick={handleReset}>重置行程</button>
          <button className="btn btn-ghost btn-sm" onClick={autoSave}>保存行程</button>
          <button
          className="btn btn-ghost btn-sm"
            onClick={() => {
                 navigate('/inspire')
            }}
              >
             返回修改
            </button>
          <button className="btn btn-primary btn-sm" onClick={handleConfirm} disabled={confirming}>
            {confirming ? '确认中...' : '确认行程'}
          </button>
        </div>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={e => setActiveId(e.active.id as string)}
        onDragEnd={handleDragEnd}
      >
        <div className="workshop-grid">
          <div className="poi-pool-panel">
            <div className="poi-tabs">
              {(['all', 'attraction', 'food', 'hotel'] as TabFilter[]).map(tab => (
                <button
                  key={tab}
                  className={`poi-tab ${activeTab === tab ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'all' ? '全部' : tab === 'attraction' ? '景点' : tab === 'food' ? '美食' : '酒店'}
                </button>
              ))}
            </div>

            {activeTab !== 'hotel' && filteredPois.map(poi => (
              <DraggablePOICard
                key={poi.id}
                poi={poi}
                isDragging={activeId === poi.id}
                onClick={() => setDetailPoi(poi)}
              />
            ))}

            {(activeTab === 'all' || activeTab === 'hotel') && (
              <div className="hotel-section">
                <div className="hotel-section-title">🏨 住宿选择（单选）</div>
                {hotels.map(hotel => (
                  <div
                    key={hotel.id}
                    className={`hotel-card ${selectedHotel?.id === hotel.id ? 'selected' : ''}`}
                    onClick={() => handleHotelChange(hotel)}
                  >
                    <img
                      className="poi-card-img"
                      src={hotel.image_url || POI_PLACEHOLDER}
                      alt={hotel.name}
                      style={{ height: 100 }}
                      loading="lazy"
                      onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
                    />
                    <div className="poi-card-body">
                      <div className="poi-card-name">{hotel.name}</div>
                      <div className="hotel-price">¥{hotel.single_night_price}/晚</div>
                      <div className="hotel-detail">
                        全程 ¥{hotel.total_accommodation_cost} | 人均 ¥{hotel.per_person_accommodation.toFixed(0)}
                      </div>
                    </div>
                  </div>
                ))}
                {selectedHotel && originalHotel && selectedHotel.id !== originalHotel.id && (
                  <button
                    className="btn btn-primary"
                    style={{ marginTop: 16, width: '100%' }}
                    onClick={() => handleReplanWithHotel()}
                    disabled={replanning}
                  >
                    {replanning ? '重新规划中...' : '🔄 按此酒店重新规划行程'}
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="timeslot-panel">
            <div className="day-tabs">
              {itinerary.map(d => (
                <button
                  key={d.day}
                  className={`day-tab ${activeDay === d.day ? 'active' : ''}`}
                  onClick={() => setActiveDay(d.day)}
                >
                  Day {d.day}
                </button>
              ))}
            </div>

            {PERIODS.map(period => (
              <div key={period.key} className="period-group">
                <div className="period-header">
                  <span className="period-icon">{period.icon}</span>
                  <span className="period-label">{period.label}</span>
                  <span className="period-time">{period.time}</span>
                </div>
                <DroppablePeriod
                  period={period.key}
                  items={getPeriodItems(period.key)}
                  poiMap={poiMap}
                  onRemove={removeFromSlot}
                  onDetail={setDetailPoi}
                />
              </div>
            ))}
          {/* ⭐ 返回酒店 */}
        <div className="period-group">
          <div className="period-header">
            <span className="period-icon">🏨</span>
            <span className="period-label">回酒店</span>
            <span className="period-time">22:00+</span>
          </div>
          <div className="period-slots">
            {selectedHotel ? (
              <div className="slot-item">
                <img
                  className="slot-item-img"
                  src={selectedHotel.image_url || POI_PLACEHOLDER}
                  alt={selectedHotel.name}
                  onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
                />
                <div className="slot-item-info">
                  <div className="slot-item-name">{selectedHotel.name}</div>
                  <div className="slot-item-cost">¥{selectedHotel.single_night_price}/晚</div>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: '#8a8580', fontSize: 12, padding: 12 }}>
                在左侧选择酒店
              </div>
            )}
          </div>
        </div>
      </div>


      <AmapView pois={mapPois} />
        </div>
      </DndContext>
            {/* 行程调整 Agent */}
      <div className="adjust-bar">
        <input
          type="text"
          value={adjustInput}
          onChange={e => setAdjustInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleAdjust() }}
          placeholder="想调整什么？例如：换掉西湖公园，换个安静的公园"
          disabled={adjusting}
          className="adjust-input"
        />
        <button
          onClick={handleAdjust}
          disabled={adjusting || !adjustInput.trim()}
          className="btn btn-primary btn-sm"
        >
          {adjusting ? '调整中...' : '发送'}
        </button>
      </div>
      {adjustMsg && <div className="adjust-msg">{adjustMsg}</div>}
      {detailPoi && (
        <POIDetailModal poi={detailPoi} onClose={() => setDetailPoi(null)} />
      )}
    </>
  )
}

function DraggablePOICard({ poi, isDragging, onClick }: {
  poi: POICard; isDragging: boolean; onClick: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging: dragging } = useDraggable({
    id: poi.id,
  })

  const style = transform ? {
    transform: CSS.Translate.toString(transform),
    opacity: dragging ? 0.5 : 1,
    zIndex: dragging ? 999 : undefined,
  } : undefined

  return (
    <div
      ref={setNodeRef}
      className={`poi-card ${isDragging ? 'dragging' : ''}`}
      style={style}
      {...listeners}
      {...attributes}
    >
      <img
        className="poi-card-img"
        src={poi.image_url || POI_PLACEHOLDER}
        alt={poi.name}
        loading="lazy"
        draggable={false}                     /* ⭐ 禁止浏览器原生拖图 */
        onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
      />
      <div className="poi-card-body" onClick={onClick}>
        <div className="poi-card-name">{poi.name}</div>
        <div className="poi-card-meta">
          <span className="score">⭐ {poi.score.toFixed(1)}</span>
          <span>¥{poi.cost}</span>
          <span>{poi.duration}分钟</span>
        </div>
        <div className="poi-card-desc">{poi.desc}</div>
      </div>
    </div>
  )
}

function DroppablePeriod({ period, items, poiMap, onRemove, onDetail }: {
  period: string
  items: TimeSlotItem[]
  poiMap: Record<string, POICard>
  onRemove: (poiId: string) => void
  onDetail: (poi: POICard) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `period-${period}` })

  return (
    <div
      ref={setNodeRef}
      className={`period-slots ${isOver ? 'drag-over' : ''}`}
    >
      {items.length === 0 && (
        <div style={{ textAlign: 'center', color: '#8a8580', fontSize: 12, padding: 12 }}>
          拖拽卡片到此处
        </div>
      )}
      {items.map(item => {
        const poi = poiMap[item.poi_id]
        if (!poi) return null
        return (
          <div key={item.poi_id} className="slot-item">
            <img
              className="slot-item-img"
              src={poi.image_url || POI_PLACEHOLDER}
              alt={poi.name}
              onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
              onClick={() => onDetail(poi)}
            />
            <div className="slot-item-info" onClick={() => onDetail(poi)} style={{ cursor: 'pointer' }}>
              <div className="slot-item-name">{poi.name}</div>
              <div className="slot-item-cost">¥{poi.cost} · {poi.duration}分钟</div>
            </div>
            <button className="slot-item-remove" onClick={() => onRemove(item.poi_id)}>×</button>
          </div>
        )
      })}
    </div>
  )
}