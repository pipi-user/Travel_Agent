/**
 * 行程详情页 — RoutePage (v2 时间轴版)
 *
 * 按天展示：时间轴 + POI 图片卡 + 交通段 + 费用汇总
 * 支持导出 Markdown / JSON
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import SimpleHeader from '../components/SimpleHeader'
import { confirmRoute, type RouteResponse } from '../api/explore'

const POI_PLACEHOLDER = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120"%3E%3Crect fill="%23f0ebe4" width="120" height="120"/%3E%3Ctext x="60" y="64" text-anchor="middle" fill="%23c4b8a8" font-size="28"%3E🏛%3C/text%3E%3C/svg%3E'

const PERIOD_META: Record<string, { label: string; icon: string; color: string }> = {
  morning:   { label: '上午', icon: '🌅', color: '#f59e0b' },
  noon:      { label: '中午', icon: '☀️', color: '#ef4444' },
  afternoon: { label: '下午', icon: '🌤', color: '#3b82f6' },
  evening:   { label: '晚上', icon: '🌙', color: '#8b5cf6' },
}

export default function RoutePage() {
  const { city } = useParams<{ city: string }>()
  const navigate = useNavigate()
  const decodedCity = decodeURIComponent(city || '')

  const [routeData, setRouteData] = useState<RouteResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeDay, setActiveDay] = useState(1)

  useEffect(() => {
    const savedRoute = sessionStorage.getItem(`travel_route_v2_${decodedCity}`)
    if (savedRoute) {
      setRouteData(JSON.parse(savedRoute))
      setLoading(false)
      return
    }
    const formData = sessionStorage.getItem('travel_form_data')
    const savedWorkshop = localStorage.getItem(`travel_workshop_v2_${decodedCity}`)
    if (!formData || !savedWorkshop) { setLoading(false); return }

    const form = JSON.parse(formData)
    const workshop = JSON.parse(savedWorkshop)
    confirmRoute({
      city: decodedCity,
      days: workshop.itinerary.length,
      slots: workshop.itinerary,
      hotel: workshop.selectedHotel,
      pois: [...(workshop.pois || []), ...(workshop.hotels || [])],
    }).then(data => {
      setRouteData(data)
      sessionStorage.setItem(`travel_route_v2_${decodedCity}`, JSON.stringify(data))
    }).catch(console.error).finally(() => setLoading(false))
  }, [decodedCity])

  const exportMarkdown = useCallback(() => {
    if (!routeData) return
    let md = `# ${decodedCity} 旅行行程\n\n`
    md += `**总花费**: ¥${routeData.total_cost.toFixed(0)}\n\n`
    if (routeData.hotel_info) {
      const h = routeData.hotel_info as any
      md += `**住宿**: ${h.name || '未选择'} ¥${h.single_night_price || 0}/晚\n\n`
    }
    routeData.days.forEach(day => {
      md += `## Day ${day.day}\n\n`
      day.items.forEach((item: any, idx: number) => {
        md += `${idx + 1}. **${item.name}** — ¥${item.cost} · ${item.duration}分钟\n`
        if (idx < day.segments.length) {
          const seg = day.segments[idx]
          md += `   → 🚗 ${seg.from_name} → ${seg.to_name} | ${seg.distance_km}km | ${seg.duration_min}分钟\n`
        }
      })
      md += `\n**当日花费**: ¥${day.daily_cost.toFixed(0)}\n\n---\n\n`
    })
    downloadFile(md, `${decodedCity}_行程.md`, 'text/markdown')
  }, [routeData, decodedCity])

  const exportJSON = useCallback(() => {
    if (!routeData) return
    downloadFile(JSON.stringify(routeData, null, 2), `${decodedCity}_行程.json`, 'application/json')
  }, [routeData])

  if (loading) {
    return (
      <>
        <SimpleHeader title={decodedCity} />
        <div className="route-loading">
          <div className="route-loading-content">
            <div className="route-loading-icon">🗺️</div>
            <div className="route-loading-title">正在规划{decodedCity}行程</div>
            <div className="route-loading-steps">
              <div className="route-loading-step done">✓ 采集景点数据</div>
              <div className="route-loading-step done">✓ 筛选特色餐厅</div>
              <div className="route-loading-step active"> 计算最优路线...</div>
              <div className="route-loading-step">○ 生成行程详情</div>
            </div>
            <div className="route-loading-bar">
              <div className="route-loading-bar-fill" style={{ width: '65%' }} />
            </div>
          </div>
        </div>
      </>
    )
  }
  if (!routeData) {
    return (
      <>
        <SimpleHeader title={decodedCity} />
        <div className="empty-state" style={{ paddingTop: 100 }}>
          <div className="empty-icon">📋</div>
          <div className="empty-text">暂无路线数据</div>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/')}>返回首页</button>
        </div>
      </>
    )
  }

  const currentDay = routeData.days.find(d => d.day === activeDay) || routeData.days[0]

  return (
    <>
      <SimpleHeader title={`${decodedCity} 行程`} />
      <div className="rp-page">
        {/* ── 顶部概览 ── */}
        <div className="rp-hero">
          <div className="rp-hero-bg" />
          <div className="rp-hero-content">
            <h1 className="rp-hero-title">{decodedCity} 之旅</h1>
            <div className="rp-hero-stats">
              <div className="rp-stat">
                <span className="rp-stat-value">{routeData.days.length}</span>
                <span className="rp-stat-label">天</span>
              </div>
              <div className="rp-stat-divider" />
              <div className="rp-stat">
                <span className="rp-stat-value">¥{routeData.total_cost.toFixed(0)}</span>
                <span className="rp-stat-label">总预算</span>
              </div>
              <div className="rp-stat-divider" />
              <div className="rp-stat">
                <span className="rp-stat-value">{routeData.days.reduce((n, d) => n + d.items.length, 0)}</span>
                <span className="rp-stat-label">个站点</span>
              </div>
            </div>
          </div>
        </div>

        {/* ── 酒店信息 ── */}
        {routeData.hotel_info && <HotelBanner hotel={routeData.hotel_info} />}

        {/* ── 日期切换 ── */}
        <div className="rp-day-tabs">
          {routeData.days.map(day => (
            <button
              key={day.day}
              className={`rp-day-tab ${activeDay === day.day ? 'active' : ''}`}
              onClick={() => setActiveDay(day.day)}
            >
              <span className="rp-day-tab-num">D{day.day}</span>
              <span className="rp-day-tab-cost">¥{day.daily_cost.toFixed(0)}</span>
            </button>
          ))}
        </div>

        {/* ── 时间轴 ── */}
        <div className="rp-timeline">
          {currentDay?.items.map((item: any, idx: number) => {
            const period = PERIOD_META[item.period] || PERIOD_META.morning
            const showTransport = idx < (currentDay?.segments?.length || 0)
            const segment = showTransport ? currentDay.segments[idx] : null

            return (
              <div key={idx} className="rp-tl-group">
                {/* POI 节点 */}
                <div className="rp-tl-node">
                  <div className="rp-tl-dot" style={{ background: period.color }} />
                  <div className="rp-tl-card">
                    <img
                      className="rp-tl-img"
                      src={item.image_url || POI_PLACEHOLDER}
                      alt={item.name}
                      loading="lazy"
                      onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
                    />
                    <div className="rp-tl-info">
                      <div className="rp-tl-badge" style={{ background: `${period.color}18`, color: period.color }}>
                        {period.icon} {period.label}
                      </div>
                      <div className="rp-tl-name">{item.name}</div>
                      <div className="rp-tl-meta">
                        {item.cost > 0 && <span className="rp-tl-cost">¥{item.cost}</span>}
                        {item.duration > 0 && <span>· {item.duration}分钟</span>}
                        {item.poi_type && (
                          <span className={`rp-tl-type rp-tl-type-${item.poi_type}`}>
                            {item.poi_type === 'attraction' ? '景点' : item.poi_type === 'food' ? '美食' : '住宿'}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 交通连接 */}
                {segment && (
                  <div className="rp-tl-transport">
                    <div className="rp-tl-line" />
                    <div className="rp-tl-seg">
                      <span className="rp-tl-seg-icon">🚗</span>
                      <span className="rp-tl-seg-text">
                        {segment.distance_km}km · {segment.duration_min}分钟
                      </span>
                    </div>
                    <div className="rp-tl-line" />
                  </div>
                )}
              </div>
            )
          })}

          {/* 当日费用小结 */}
          {currentDay && (
            <div className="rp-tl-summary">
              <div className="rp-tl-summary-row">
                <span>当日花费</span>
                <strong>¥{currentDay.daily_cost.toFixed(0)}</strong>
              </div>
              <div className="rp-tl-summary-row">
                <span>站点数</span>
                <strong>{currentDay.items.length} 个</strong>
              </div>
            </div>
          )}
        </div>

        {/* ── 总费用汇总 ── */}
        <div className="rp-total-bar">
          <div className="rp-total-label">全程总费用</div>
          <div className="rp-total-value">¥{routeData.total_cost.toFixed(0)}</div>
        </div>

        {/* ── 操作按钮 ── */}
        <div className="rp-actions">
          <button className="btn btn-secondary" onClick={exportMarkdown}>📄 导出 Markdown</button>
          <button className="btn btn-secondary" onClick={exportJSON}>📋 导出 JSON</button>
          <button className="btn btn-ghost" onClick={() => navigate(`/workshop/${encodeURIComponent(decodedCity)}`)}>
            ← 返回编辑
          </button>
          <button className="btn btn-ghost" onClick={() => navigate('/inspire')}>
            🏠 返回首页
          </button>
        </div>
      </div>
    </>
  )
}

/* ═══════════ 子组件 ═══════════ */

function HotelBanner({ hotel }: { hotel: any }) {
  const h = hotel
  return (
    <div className="rp-hotel-banner">
      <div className="rp-hotel-left">
        <span className="rp-hotel-icon">🏨</span>
        <div>
          <div className="rp-hotel-name">{h.name || '住宿'}</div>
          <div className="rp-hotel-sub">¥{h.single_night_price}/晚 · 全程¥{h.total_accommodation_cost} · 人均¥{h.per_person_accommodation?.toFixed(0)}</div>
        </div>
      </div>
      {h.image_url && (
        <img className="rp-hotel-thumb" src={h.image_url} alt={h.name} loading="lazy" />
      )}
    </div>
  )
}

/* ═══════════ 工具 ═══════════ */

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
