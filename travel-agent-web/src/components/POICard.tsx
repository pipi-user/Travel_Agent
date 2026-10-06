import { useState } from 'react'
import type { POICard as POICardType } from '../api'

interface Props {
  poi: POICardType
  compact?: boolean
  onLike?: () => void
  onDislike?: () => void
  onVisit?: () => void
  onDragStart?: () => void
  liked?: boolean
  disliked?: boolean
}

const TYPE_ICON: Record<string, string> = { attraction: '🏛️', food: '🍜', hotel: '🏨', transport: '' }
const TYPE_COLOR: Record<string, string> = { attraction: '#4a90d9', food: '#e08030', hotel: '#2ecc71', transport: '#9b59b6' }

export default function POICardView({ poi, compact, onLike, onDislike, onVisit, onDragStart, liked, disliked }: Props) {
  const [showActions, setShowActions] = useState(false)

  return (
    <div
      className={`poi-card ${compact ? 'compact' : ''} ${liked ? 'liked' : ''} ${disliked ? 'disliked' : ''}`}
      style={{ borderLeftColor: TYPE_COLOR[poi.type] || '#888' }}
      draggable={!!onDragStart}
      onDragStart={onDragStart}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      {/* 封面图 */}
      {poi.cover_image && (
        <div className="poi-cover" style={{ backgroundImage: `url(${poi.cover_image})` }} />
      )}

      <div className="poi-body">
        <div className="poi-header">
          <span className="poi-type-icon">{TYPE_ICON[poi.type] || ''}</span>
          <h4 className="poi-name">{poi.name}</h4>
        </div>

        {!compact && (
          <>
            {poi.description && <p className="poi-desc">{poi.description}</p>}
            {poi.tags.length > 0 && (
              <div className="poi-tags">
                {poi.tags.map(t => <span key={t} className="poi-tag">{t}</span>)}
              </div>
            )}
            <div className="poi-meta">
              {poi.rating !== '暂无' && <span className="poi-rating">★ {poi.rating}</span>}
              {poi.cost !== '暂无' && <span className="poi-cost">{poi.cost}</span>}
              {poi.duration_min > 0 && <span className="poi-duration">⏱ {poi.duration_min}分钟</span>}
            </div>
          </>
        )}

        {compact && (
          <div className="poi-meta-compact">
            {poi.rating !== '暂无' && <span>★{poi.rating}</span>}
            {poi.cost !== '暂无' && <span>{poi.cost}</span>}
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      {(onLike || onDislike || onVisit) && (
        <div className={`poi-actions ${showActions || liked || disliked ? 'visible' : ''}`}>
          {onLike && (
            <button className={`action-btn like-btn ${liked ? 'active' : ''}`} onClick={onLike} title="喜欢">
              {liked ? '❤️' : ''}
            </button>
          )}
          {onDislike && (
            <button className={`action-btn dislike-btn ${disliked ? 'active' : ''}`} onClick={onDislike} title="不喜欢">
              {disliked ? '👎' : '👎🏻'}
            </button>
          )}
          {onVisit && (
            <button className="action-btn visit-btn" onClick={onVisit} title="标记去过">
              📍
            </button>
          )}
        </div>
      )}
    </div>
  )
}
