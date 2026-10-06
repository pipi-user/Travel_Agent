/**
 * 行程规划 API 调用层
 */

const BASE_URL = 'http://localhost:8000'

export interface ArrangeParams {
  user_id?: string
  request: any
  city: string
  days: { day: number; items: string[] }[]
  poi_pool: any[]
  hotel?: any
  pace: string
}

export interface ArrangeResponse {
  itinerary: any
}

/** 提交行程并获取优化路线 */
export async function arrangeItinerary(params: ArrangeParams): Promise<ArrangeResponse> {
  const res = await fetch(`${BASE_URL}/api/plan/arrange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error('生成行程路线失败')
  return await res.json()
}
