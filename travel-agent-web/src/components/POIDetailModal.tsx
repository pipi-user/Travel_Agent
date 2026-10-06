/**
 * POI 详情弹窗
 * 
 * 点击 POI 卡片唤起，展示完整信息
 * 外链按钮：小红书 / 抖音 / 百度，全部 target="_blank"
 */

import type { POICard } from '../api/explore'

interface POIDetailModalProps {
  poi: POICard
  onClose: () => void
}

const POI_PLACEHOLDER = '/assets/poi/placeholder.svg'

export default function POIDetailModal({ poi, onClose }: POIDetailModalProps) {
  const name = poi.name || '未知'

  // 外链
  const xiaohongshuUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(name)}`
  const douyinUrl = `https://www.douyin.com/search/${encodeURIComponent(name)}`
  const baiduUrl = `https://www.baidu.com/s?wd=${encodeURIComponent(name + ' 旅游攻略')}`

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{ position: 'relative' }}>
        <button className="modal-close" onClick={onClose}>×</button>
        <img
          className="modal-img"
          src={poi.image_url || POI_PLACEHOLDER}
          alt={name}
          onError={e => { (e.target as HTMLImageElement).src = POI_PLACEHOLDER }}
        />
        <div className="modal-body">
          <div className="modal-name">{name}</div>
          <div className="modal-meta">
            <span>⭐ {poi.score.toFixed(1)}</span>
            <span>💰 ¥{poi.cost}</span>
            <span>⏱ {poi.duration}分钟</span>
            {poi.tags.length > 0 && <span>{poi.tags.join(' · ')}</span>}
          </div>
          <div className="modal-desc">
            {poi.desc || poi.address || '暂无详细介绍'}
          </div>
          <div className="modal-links">
            <a className="modal-link" href={xiaohongshuUrl} target="_blank" rel="noopener noreferrer">
              📕 小红书
            </a>
            <a className="modal-link" href={douyinUrl} target="_blank" rel="noopener noreferrer">
              🎵 抖音
            </a>
            <a className="modal-link" href={baiduUrl} target="_blank" rel="noopener noreferrer">
              🔍 百度
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
