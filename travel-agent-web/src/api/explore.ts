/**
 * 灵感漫游 API 客户端
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// ─── 类型 ──────────────────────────────────────────

export interface ExploreCitiesRequest {
  origin: string
  budget: number
  days: number
  companions: number
  preferences?: string[]
  intensity: '边走边躺' | '莫名其妙地玩' | '死了都要逛'
}

export interface CityCandidate {
  city: string
  score: number
  reason: string
  tags: string[]
  daily_cost: number
  intro: string
  image_url: string
}

export interface ExploreCitiesResponse {
  candidates: CityCandidate[]
}

export interface POICard {
  id: string
  name: string
  poi_type: 'attraction' | 'food' | 'hotel'
  score: number
  cost: number
  duration: number
  lat: number
  lng: number
  image_url: string
  tags: string[]
  desc?: string
  address?: string
}

export interface HotelPOI extends POICard {
  poi_type: 'hotel'
  single_night_price: number
  total_accommodation_cost: number
  per_person_accommodation: number
}

export interface TimeSlotItem {
  poi_id: string
  period: 'morning' | 'noon' | 'afternoon' | 'evening'
}

export interface DaySchedule {
  day: number
  items: TimeSlotItem[]
}

export interface TransportSegment {
  from_name: string
  to_name: string
  distance_km: number
  duration_min: number
  mode: string
  cost: number
}

export interface RouteDay {
  day: number
  items: POICard[]
  segments: TransportSegment[]
  daily_cost: number
}

export interface RouteResponse {
  city: string
  days: RouteDay[]
  hotel_info: HotelPOI | null
  total_cost: number
}

export interface ExplorePoisResponse {
  city: string
  pois: POICard[]
  hotels: HotelPOI[]
  initial_itinerary: DaySchedule[]
}

// ─── 调用 ──────────────────────────────────────────

export async function fetchCities(req: ExploreCitiesRequest): Promise<ExploreCitiesResponse> {
  const res = await fetch(`${API_BASE}/api/explore/cities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`获取城市推荐失败: ${res.statusText}`)
  return res.json()
}

export async function fetchPOIs(payload: {
  city: string
  budget: number
  companions: number
  days: number
  intensity: string
  preferences: string[]
}): Promise<ExplorePoisResponse> {
  const res = await fetch(`${API_BASE}/api/explore/pois`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`获取 ${payload.city} POI 失败: ${res.statusText}`)
  return res.json()
}

export async function confirmRoute(payload: {
  city: string
  days: number
  slots: DaySchedule[]
  hotel: HotelPOI | null
  pois: POICard[]
}): Promise<RouteResponse> {
  const res = await fetch(`${API_BASE}/api/plan/route`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`确认路线失败: ${res.statusText}`)
  return res.json()
}
export async function adjustItinerary(payload: {
  city: string
  message: string
  itinerary: DaySchedule[]
  pois: POICard[]
}): Promise<{ itinerary: DaySchedule[]; text: string; success: boolean }> {
  const res = await fetch(`${API_BASE}/api/inspire/adjust`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`调整失败：${res.statusText}`)
  return res.json()
}

export async function replanItinerary(payload: {
  city: string
  hotel_id: string
  pois: POICard[]
  hotels: HotelPOI[]
  days: number
}): Promise<{ itinerary: DaySchedule[]; hotel: HotelPOI }> {
  const res = await fetch(`${API_BASE}/api/explore/replan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`重新规划失败：${res.statusText}`)
  return res.json()
}