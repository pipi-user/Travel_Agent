import { useState } from 'react'
import { apiExploreCities, apiExplorePois, DEMO_CITIES, DEMO_POIS } from '../api'
import type { POICard, TripRequest } from '../api'
import POICardView from './POICard'

const PREFS = ['自然风光', '历史人文', '美食体验', '户外探险', '休闲度假', '摄影打卡', '亲子', '购物']
const PACES = ['轻松', '适中', '紧凑']
const COMPANIONS = ['独自', '情侣', '朋友', '家庭']

interface Props {
  userId: string
  onGoPlanner: (city: string, pois: { attractions: POICard[]; foods: POICard[]; hotels: POICard[] }, request: Partial<TripRequest>) => void
}

export default function Explore({ userId, onGoPlanner }: Props) {
  const [step, setStep] = useState<'form' | 'cities' | 'pois'>('form')
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState({ origin: '', budget: 5000, days: 3, month: new Date().getMonth() + 1, preferences: [] as string[], pace: '适中', companions: '独自' })
  const [cities, setCities] = useState(DEMO_CITIES)
  const [pois, setPois] = useState<{ attractions: POICard[]; foods: POICard[]; hotels: POICard[] } | null>(null)
  const [selectedCity, setSelectedCity] = useState('')
  const [error, setError] = useState('')

  const togglePref = (p: string) => setForm(f => ({ ...f, preferences: f.preferences.includes(p) ? f.preferences.filter(x => x !== p) : [...f.preferences, p] }))

  const handleSearch = async () => {
    if (!form.origin.trim()) { setError('请填写出发地'); return }
    setLoading(true); setError('')
    try {
      const res = await apiExploreCities({ user_id: userId, ...form })
      setCities(res.candidates)
    } catch { setCities(DEMO_CITIES) }
    setStep('cities'); setLoading(false)
  }

  const handleSelectCity = async (city: string) => {
    setSelectedCity(city); setLoading(true)
    try {
      const res = await apiExplorePois({ user_id: userId, city, preferences: form.preferences, days: form.days, companions: form.companions })
      setPois({ attractions: res.attractions, foods: res.foods, hotels: res.hotels })
    } catch {
      setPois({ attractions: DEMO_POIS.attractions, foods: DEMO_POIS.foods, hotels: DEMO_POIS.hotels })
    }
    setStep('pois'); setLoading(false)
  }

  const handleGoPlanner = () => {
    if (pois) onGoPlanner(selectedCity, pois, form)
  }

  return (
    <div className="page explore-page">
      {step === 'form' && (
        <div className="explore-form fade-in">
          <h2 className="page-title">想去哪里？告诉我你的偏好</h2>
          <p className="page-subtitle">AI 将根据你的喜好推荐最佳目的地</p>
          <div className="form-grid">
            <div className="form-group">
              <label>出发地</label>
              <input value={form.origin} onChange={e => setForm(f => ({ ...f, origin: e.target.value }))} placeholder="如：深圳" />
            </div>
            <div className="form-group">
              <label>预算 (元)</label>
              <input type="number" value={form.budget} onChange={e => setForm(f => ({ ...f, budget: +e.target.value }))} />
            </div>
            <div className="form-group">
              <label>天数</label>
              <input type="number" min={1} max={15} value={form.days} onChange={e => setForm(f => ({ ...f, days: +e.target.value }))} />
            </div>
            <div className="form-group">
              <label>出行月份</label>
              <input type="number" min={1} max={12} value={form.month} onChange={e => setForm(f => ({ ...f, month: +e.target.value }))} />
            </div>
          </div>
          <div className="form-section">
            <label className="section-label">旅行偏好</label>
            <div className="pref-tags">
              {PREFS.map(p => (
                <button key={p} className={`pref-tag ${form.preferences.includes(p) ? 'active' : ''}`} onClick={() => togglePref(p)}>{p}</button>
              ))}
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>节奏</label>
              <div className="seg-group">
                {PACES.map(p => <button key={p} className={`seg-btn ${form.pace === p ? 'active' : ''}`} onClick={() => setForm(f => ({ ...f, pace: p }))}>{p}</button>)}
              </div>
            </div>
            <div className="form-group">
              <label>同行</label>
              <div className="seg-group">
                {COMPANIONS.map(c => <button key={c} className={`seg-btn ${form.companions === c ? 'active' : ''}`} onClick={() => setForm(f => ({ ...f, companions: c }))}>{c}</button>)}
              </div>
            </div>
          </div>
          {error && <p className="error-msg">{error}</p>}
          <button className="primary-btn" onClick={handleSearch} disabled={loading}>
            {loading ? 'AI 推荐中...' : '开始探索'}
          </button>
        </div>
      )}

      {step === 'cities' && (
        <div className="explore-cities fade-in">
          <div className="page-header-row">
            <div>
              <h2 className="page-title">为你推荐</h2>
              <p className="page-subtitle">点击城市查看详细信息</p>
            </div>
            <button className="secondary-btn" onClick={() => setStep('form')}>← 修改条件</button>
          </div>
          <div className="city-grid">
            {cities.map((c, i) => (
              <div key={i} className="city-card" onClick={() => handleSelectCity(c.city)}>
                <div className="city-score">{c.score}</div>
                <h3>{c.city}</h3>
                <p>{c.reason}</p>
                <div className="city-meta">
                  <span>¥{c.estimated_cost}</span>
                  <span>{c.weather}</span>
                </div>
                <button className="select-btn">查看 POI</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {step === 'pois' && pois && (
        <div className="explore-pois fade-in">
          <div className="page-header-row">
            <div>
              <h2 className="page-title">{selectedCity} 精彩去处</h2>
              <p className="page-subtitle">拖拽卡片到规划页定制你的行程</p>
            </div>
            <div className="header-actions">
              <button className="secondary-btn" onClick={() => setStep('cities')}>← 换城市</button>
              <button className="primary-btn" onClick={handleGoPlanner}>进入规划</button>
            </div>
          </div>
          <div className="poi-sections">
            <div className="poi-section">
              <h3 className="section-title">景点 ({pois.attractions.length})</h3>
              <div className="poi-grid">
                {pois.attractions.map(p => <POICardView key={p.id} poi={p} />)}
              </div>
            </div>
            <div className="poi-section">
              <h3 className="section-title">美食 ({pois.foods.length})</h3>
              <div className="poi-grid">
                {pois.foods.map(p => <POICardView key={p.id} poi={p} />)}
              </div>
            </div>
            <div className="poi-section">
              <h3 className="section-title">住宿 ({pois.hotels.length})</h3>
              <div className="poi-grid">
                {pois.hotels.map(p => <POICardView key={p.id} poi={p} />)}
              </div>
            </div>
          </div>
        </div>
      )}

      {loading && <div className="loading-overlay"><div className="spinner" /></div>}
    </div>
  )
}
