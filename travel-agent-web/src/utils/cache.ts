/**
 * 旅行搜索记录缓存
 * 使用 localStorage 保存用户的搜索历史
 */

export interface TravelCacheRecord {
  id: string
  timestamp: number
  destination: string  // 目的地城市（作为标题）
  origin: string
  budgetMin: number
  budgetMax: number
  days: number
  pace: string
  companions: string
  companionCount: number
  preferences: string[]
  customPreference: string
  age: number
  cities: Array<{
    city: string
    score: number
    reason: string
    image?: string
  }>
}

const CACHE_KEY = 'travel_agent_cache'
const MAX_CACHE_RECORDS = 20  // 最多保存 20 条记录

/** 获取所有缓存记录 */
export function getCacheRecords(): TravelCacheRecord[] {
  try {
    const data = localStorage.getItem(CACHE_KEY)
    if (!data) return []
    return JSON.parse(data)
  } catch {
    return []
  }
}

/** 保存一条缓存记录 */
export function saveCacheRecord(record: Omit<TravelCacheRecord, 'id' | 'timestamp'>): TravelCacheRecord {
  const records = getCacheRecords()
  const newRecord: TravelCacheRecord = {
    ...record,
    id: `cache_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    timestamp: Date.now(),
  }
  // 添加到开头，限制数量
  records.unshift(newRecord)
  const trimmed = records.slice(0, MAX_CACHE_RECORDS)
  localStorage.setItem(CACHE_KEY, JSON.stringify(trimmed))
  return newRecord
}

/** 删除一条缓存记录 */
export function deleteCacheRecord(id: string): void {
  const records = getCacheRecords().filter(r => r.id !== id)
  localStorage.setItem(CACHE_KEY, JSON.stringify(records))
}

/** 清空所有缓存记录 */
export function clearAllCache(): void {
  localStorage.removeItem(CACHE_KEY)
}
