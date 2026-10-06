/**
 * 旧版 API 客户端（兼容保留）
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

export async function chat(message: string) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`);
  return res.json();
}
