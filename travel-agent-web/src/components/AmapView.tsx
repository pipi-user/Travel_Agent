/**
 * 高德地图组件 — AmapView v3
 */

import { useState, useEffect, useRef } from 'react'

interface MapPOI {
  id: string
  name: string
  lat: number
  lng: number
  poi_type: string
}

interface AmapViewProps {
  pois: MapPOI[]
  center?: { lat: number; lng: number }
  activeId?: string | null
  onMarkerClick?: (id: string) => void
}

const AMAP_KEY = '195a0216a0f852b8a2c7315f3d82fed9'

const TYPE_COLOR: Record<string, string> = {
  attraction: '#d4a853',
  food: '#e8746a',
  hotel: '#5b8def',
}

export default function AmapView({ pois, center, activeId, onMarkerClick }: AmapViewProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [mapError, setMapError] = useState(false)
  const [mapReady, setMapReady] = useState(false)   // ⭐ 新增
  const mapRef = useRef<HTMLDivElement>(null)
  const amapInstance = useRef<any>(null)
  const markersRef = useRef<Map<string, any>>(new Map())
  const polylineRef = useRef<any>(null)
  const lastFitKey = useRef<string>('')
  const initializingRef = useRef(false)             // ⭐ 防止重复初始化

  // 初始化地图
  useEffect(() => {
    if (collapsed || mapError) return
    if (initializingRef.current) return             // ⭐ 已在初始化中
    if (amapInstance.current) return                // ⭐ 已初始化

    initializingRef.current = true

    const initMap = async () => {
      try {
        const AMapLoader = await import('@amap/amap-jsapi-loader')
        const AMap = await AMapLoader.default.load({
          key: AMAP_KEY,
          version: '2.0',
          plugins: ['AMap.Marker', 'AMap.Polyline'],
        })

        if (!mapRef.current) {
          initializingRef.current = false
          return
        }
        // ⭐ 二次检查，防止 React StrictMode 下两个实例都创建
        if (amapInstance.current) {
          initializingRef.current = false
          return
        }

        const defaultCenter = center
          ? [center.lng, center.lat]
          : (pois.length > 0 ? [pois[0].lng, pois[0].lat] : [116.397428, 39.90923])

        const map = new AMap.Map(mapRef.current, {
          zoom: 13,
          center: defaultCenter,
          viewMode: '2D',
          mapStyle: 'amap://styles/whitesmoke',
        })
        amapInstance.current = map
        setMapReady(true)                            // ⭐ 通知 marker effect
        initializingRef.current = false
      } catch (e) {
        console.error('高德地图加载失败', e)
        setMapError(true)
        initializingRef.current = false
      }
    }

    initMap()
  }, [collapsed, mapError])

  // ⭐ 只在组件真正卸载时 destroy
  useEffect(() => {
    return () => {
      // 延迟 destroy，避免 StrictMode 的假卸载
      const instance = amapInstance.current
      setTimeout(() => {
        if (instance && !document.contains(mapRef.current)) {
          instance.destroy?.()
        }
      }, 100)
    }
  }, [])

  // 更新标记 —— ⭐ 依赖 mapReady
  useEffect(() => {
    if (!mapReady || !amapInstance.current || collapsed) return
    const AMap = (window as any).AMap
    if (!AMap) return

    markersRef.current.forEach(m => m.setMap?.(null))
    markersRef.current.clear()
    if (polylineRef.current) {
      polylineRef.current.setMap?.(null)
      polylineRef.current = null
    }

    if (pois.length === 0) {
      lastFitKey.current = ''
      return
    }

    const path: [number, number][] = []

    pois.forEach((poi, idx) => {
      if (!poi.lat || !poi.lng) return

      const color = TYPE_COLOR[poi.poi_type] || '#d4a853'
      const num = idx + 1
      const shortName = poi.name.length > 8 ? poi.name.slice(0, 8) + '…' : poi.name

      const marker = new AMap.Marker({
        position: [poi.lng, poi.lat],
        title: poi.name,
        anchor: 'center',
        content: `
          <div style="
            display:flex;align-items:center;gap:5px;
            background:rgba(255,255,255,0.96);
            padding:3px 9px 3px 3px;
            border-radius:20px;
            border:1.5px solid ${color};
            box-shadow:0 2px 8px rgba(0,0,0,0.18);
            cursor:pointer;
            white-space:nowrap;
          ">
            <span style="
              width:22px;height:22px;border-radius:50%;
              background:${color};
              color:#fff;font-weight:700;font-size:12px;
              display:flex;align-items:center;justify-content:center;
              flex-shrink:0;
            ">${num}</span>
            <span style="color:#3a3632;font-size:12px;font-weight:500;">${shortName}</span>
          </div>
        `,
      })

      marker.setMap(amapInstance.current)
      if (onMarkerClick) {
        marker.on('click', () => onMarkerClick(poi.id))
      }
      markersRef.current.set(poi.id, marker)
      path.push([poi.lng, poi.lat])
    })

    if (path.length > 1) {
      const polyline = new AMap.Polyline({
        path,
        strokeColor: '#d4a853',
        strokeWeight: 3,
        strokeOpacity: 0.75,
        strokeStyle: 'dashed',
        lineJoin: 'round',
        showDir: true,
      })
      polyline.setMap(amapInstance.current)
      polylineRef.current = polyline
    }

    const fitKey = pois.map(p => p.id).join(',')
    if (fitKey !== lastFitKey.current && path.length > 0) {
      lastFitKey.current = fitKey
      amapInstance.current.setFitView(null, false, [80, 80, 80, 80])
    }
  }, [pois, mapReady, collapsed])

  return (
    <div className="map-panel">
      <div className="map-panel-header">
        <span className="map-panel-title">🗺️ 地图</span>
        <div className="map-legend">
          <span><i style={{ background: TYPE_COLOR.attraction }} /> 景点</span>
          <span><i style={{ background: TYPE_COLOR.food }} /> 美食</span>
          <span><i style={{ background: TYPE_COLOR.hotel }} /> 酒店</span>
        </div>
        <button className="map-toggle-btn" onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? '展开' : '收起'}
        </button>
      </div>
      {!collapsed && (
        <div className="map-container">
          {mapError ? (
            <div className="map-placeholder">
              <span>🗺️ 地图暂不可用</span>
            </div>
          ) : (
            <div ref={mapRef} style={{ width: '100%', height: '100%' }} />
          )}
        </div>
      )}
    </div>
  )
}