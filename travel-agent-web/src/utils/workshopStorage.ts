/**
 * localStorage 持久化工具
 * 
 * 每次拖拽、删除、切换酒店操作自动实时保存行程状态
 * localStorage 不可用时降级内存存储
 */

import type { DaySchedule, POICard, HotelPOI } from '../api/explore'

interface WorkshopState {
  itinerary: DaySchedule[]
  selectedHotel: HotelPOI | null
  pois: POICard[]
  hotels: HotelPOI[]
}

const memoryStore = new Map<string, WorkshopState>()

function isLocalStorageAvailable(): boolean {
  try {
    const test = '__ls_test__'
    localStorage.setItem(test, test)
    localStorage.removeItem(test)
    return true
  } catch {
    return false
  }
}

const useMemory = !isLocalStorageAvailable()

function getKey(city: string): string {
  return `travel_workshop_v2_${city}`  // v2: 修复时段分配逻辑
}

export function saveWorkshop(city: string, state: WorkshopState): void {
  const key = getKey(city)
  try {
    if (useMemory) {
      memoryStore.set(key, state)
    } else {
      localStorage.setItem(key, JSON.stringify(state))
    }
  } catch (e) {
    console.warn('保存行程状态失败，降级内存存储', e)
    memoryStore.set(key, state)
  }
}

export function loadWorkshop(city: string): WorkshopState | null {
  const key = getKey(city)
  try {
    if (useMemory) {
      return memoryStore.get(key) || null
    }
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as WorkshopState
  } catch (e) {
    console.warn('加载行程状态失败', e)
    return memoryStore.get(key) || null
  }
}

export function clearWorkshop(city: string): void {
  const key = getKey(city)
  try {
    if (useMemory) {
      memoryStore.delete(key)
    } else {
      localStorage.removeItem(key)
    }
  } catch (e) {
    console.warn('清除行程状态失败', e)
    memoryStore.delete(key)
  }
}
