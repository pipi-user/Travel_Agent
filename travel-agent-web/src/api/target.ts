/**
 * 定向定制 API 调用层
 */

const BASE_URL = 'http://localhost:8000'

export interface TargetPlanParams {
  user_id?: string
  origin: string
  dest_city: string
  start_date: string
  days: number
  pace: string
  companions: string
  extra_notes: string
}

export interface DaySlot {
  day: number
  items: string[]
}

export interface TargetPlanResponse {
  city: string
  attractions: any[]
  foods: any[]
  hotels: any[]
  default_slots: DaySlot[]
  itinerary: any
}

/** 获取定向定制行程 */
export async function fetchTargetPlan(params: TargetPlanParams): Promise<TargetPlanResponse> {
  const res = await fetch(`${BASE_URL}/api/target/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error('生成行程失败')
  return await res.json()
}
