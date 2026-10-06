import { useState, useEffect } from 'react'
import { apiGetProfile, apiSaveProfile, apiListMemories, apiDeleteMemory, apiClearMemories, apiSearchMemories } from '../api'
import type { UserProfile, MemoryRecord } from '../api'

interface Props { userId: string }

export default function Memory({ userId }: Props) {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [memories, setMemories] = useState<MemoryRecord[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<MemoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [editingProfile, setEditingProfile] = useState(false)
  const [profileDraft, setProfileDraft] = useState<UserProfile>({ allergies: [], fears: [], dietary: [], pace_preference: '' })
  const [newAllergy, setNewAllergy] = useState('')
  const [newFear, setNewFear] = useState('')
  const [newDietary, setNewDietary] = useState('')

  // 加载数据
  useEffect(() => {
    loadData()
  }, [userId])

  const loadData = async () => {
    setLoading(true)
    try {
      const [p, m] = await Promise.all([
        apiGetProfile(userId).catch(() => ({ allergies: [], fears: [], dietary: [], pace_preference: null })),
        apiListMemories(userId).catch(() => ({ memories: [] })),
      ])
      setProfile(p)
      setMemories(m.memories)
      setProfileDraft({ ...p, pace_preference: p.pace_preference || '' })
    } catch { /* ignore */ }
    setLoading(false)
  }

  // 保存画像
  const handleSaveProfile = async () => {
    try {
      await apiSaveProfile(userId, profileDraft)
      setProfile(profileDraft)
      setEditingProfile(false)
    } catch { /* ignore */ }
  }

  // 添加画像标签
  const addTag = (field: 'allergies' | 'fears' | 'dietary', value: string) => {
    if (!value.trim()) return
    setProfileDraft(d => ({ ...d, [field]: [...d[field], value.trim()] }))
    if (field === 'allergies') setNewAllergy('')
    if (field === 'fears') setNewFear('')
    if (field === 'dietary') setNewDietary('')
  }

  const removeTag = (field: 'allergies' | 'fears' | 'dietary', idx: number) => {
    setProfileDraft(d => ({ ...d, [field]: d[field].filter((_, i) => i !== idx) }))
  }

  // 搜索记忆
  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults([]); return }
    try {
      const res = await apiSearchMemories(userId, searchQuery)
      setSearchResults(res.results)
    } catch { setSearchResults([]) }
  }

  // 删除记忆
  const handleDelete = async (id: number) => {
    try {
      await apiDeleteMemory(userId, id)
      setMemories(prev => prev.filter(m => m.id !== id))
    } catch { /* ignore */ }
  }

  // 清空记忆
  const handleClear = async () => {
    if (!confirm('确定清空所有记忆？')) return
    try {
      await apiClearMemories(userId)
      setMemories([])
    } catch { /* ignore */ }
  }

  // 分类记忆
  const grouped = memories.reduce<Record<string, MemoryRecord[]>>((acc, m) => {
    (acc[m.type] ||= []).push(m)
    return acc
  }, {})

  const typeLabels: Record<string, { label: string; icon: string; color: string }> = {
    liked: { label: '喜欢', icon: '❤️', color: '#e74c3c' },
    disliked: { label: '不喜欢', icon: '👎', color: '#95a5a6' },
    visited: { label: '去过', icon: '📍', color: '#2ecc71' },
    preference: { label: '偏好', icon: '⭐', color: '#f0c040' },
    note: { label: '备注', icon: '', color: '#3498db' },
  }

  return (
    <div className="page memory-page">
      <div className="memory-layout">
        {/* 左侧：用户画像 */}
        <div className="profile-panel fade-in">
          <div className="profile-header">
            <h2 className="panel-title">用户画像</h2>
            <button className="icon-btn" onClick={() => { setEditingProfile(!editingProfile); if (!editingProfile) setProfileDraft({ ...profile!, pace_preference: profile?.pace_preference || '' }) }}>
              {editingProfile ? '✕' : '✎'}
            </button>
          </div>

          {editingProfile ? (
            <div className="profile-edit">
              {(['allergies', 'fears', 'dietary'] as const).map(field => {
                const labels = { allergies: '过敏', fears: '恐惧', dietary: '饮食禁忌' }
                const values = { allergies: newAllergy, fears: newFear, dietary: newDietary }
                const setters = { allergies: setNewAllergy, fears: setNewFear, dietary: setNewDietary }
                return (
                  <div key={field} className="profile-field">
                    <label>{labels[field]}</label>
                    <div className="tag-list">
                      {profileDraft[field].map((t, i) => (
                        <span key={i} className="tag-item">{t}<button onClick={() => removeTag(field, i)}>×</button></span>
                      ))}
                    </div>
                    <div className="tag-input-row">
                      <input value={values[field]} onChange={e => setters[field](e.target.value)} placeholder={`添加${labels[field]}`} onKeyDown={e => e.key === 'Enter' && addTag(field, values[field])} />
                      <button onClick={() => addTag(field, values[field])}>+</button>
                    </div>
                  </div>
                )
              })}
              <div className="profile-field">
                <label>节奏偏好</label>
                <div className="seg-group">
                  {['轻松', '适中', '紧凑'].map(p => (
                    <button key={p} className={`seg-btn ${profileDraft.pace_preference === p ? 'active' : ''}`} onClick={() => setProfileDraft(d => ({ ...d, pace_preference: p }))}>{p}</button>
                  ))}
                </div>
              </div>
              <button className="primary-btn small" onClick={handleSaveProfile}>保存画像</button>
            </div>
          ) : profile ? (
            <div className="profile-view">
              {(['allergies', 'fears', 'dietary'] as const).map(field => {
                const labels = { allergies: '过敏', fears: '恐惧', dietary: '饮食禁忌' }
                return profile[field].length > 0 ? (
                  <div key={field} className="profile-row">
                    <span className="profile-label">{labels[field]}</span>
                    <div className="profile-tags">
                      {profile[field].map((t, i) => <span key={i} className="profile-tag">{t}</span>)}
                    </div>
                  </div>
                ) : null
              })}
              {profile.pace_preference && (
                <div className="profile-row">
                  <span className="profile-label">节奏</span>
                  <span className="profile-value">{profile.pace_preference}</span>
                </div>
              )}
              {Object.values(profile).every(v => !v || (Array.isArray(v) && v.length === 0)) && (
                <p className="profile-empty">暂无画像数据，点击右上角编辑</p>
              )}
            </div>
          ) : null}

          {/* 记忆统计 */}
          <div className="memory-stats">
            <h3 className="stats-title">记忆统计</h3>
            <div className="stats-grid">
              {Object.entries(typeLabels).map(([type, info]) => (
                <div key={type} className="stat-card" style={{ borderColor: info.color }}>
                  <span className="stat-icon">{info.icon}</span>
                  <span className="stat-count">{grouped[type]?.length || 0}</span>
                  <span className="stat-name">{info.label}</span>
                </div>
              ))}
            </div>
            <button className="danger-btn" onClick={handleClear}>清空记忆</button>
          </div>
        </div>

        {/* 右侧：记忆列表 + 搜索 */}
        <div className="memories-panel fade-in">
          <div className="search-bar">
            <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()} placeholder="语义搜索记忆..." />
            <button onClick={handleSearch}>搜索</button>
          </div>

          {searchResults.length > 0 && (
            <div className="search-results">
              <h4>搜索结果 ({searchResults.length})</h4>
              {searchResults.map(m => (
                <div key={m.id} className="memory-item search-hit">
                  <span className="memory-type" style={{ background: typeLabels[m.type]?.color || '#888' }}>{typeLabels[m.type]?.icon || ''}</span>
                  <div className="memory-content"><p>{m.text}</p>{m.metadata?.city && <span className="memory-meta">{m.metadata.city}</span>}</div>
                </div>
              ))}
            </div>
          )}

          {/* 分类记忆列表 */}
          {Object.entries(typeLabels).map(([type, info]) => {
            const items = grouped[type] || []
            if (items.length === 0) return null
            return (
              <div key={type} className="memory-group">
                <h4 className="group-title" style={{ color: info.color }}>{info.icon} {info.label} ({items.length})</h4>
                <div className="memory-list">
                  {items.map(m => (
                    <div key={m.id} className="memory-item">
                      <div className="memory-content">
                        <p>{m.text}</p>
                        {m.metadata?.city && <span className="memory-meta">{m.metadata.city}</span>}
                      </div>
                      <button className="memory-delete" onClick={() => handleDelete(m.id)}>×</button>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}

          {memories.length === 0 && (
            <div className="memory-empty">
              <p>还没有记忆记录</p>
              <p className="memory-empty-hint">在规划页对 POI 点 ❤️/，或完成行程后提取记忆</p>
            </div>
          )}
        </div>
      </div>

      {loading && <div className="loading-overlay"><div className="spinner" /></div>}
    </div>
  )
}
