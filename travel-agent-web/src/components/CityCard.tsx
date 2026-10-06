/**
 * 城市推荐卡片
 *
 * 图片策略（三级兜底）：
 * 1. 后端返回的 city.image_url（静态服务 / Tavily）
 * 2. 本地映射 /assets/city/{slug}.webp
 * 3. placeholder.svg
 */

import { useState, useEffect } from 'react'
import type { CityCandidate } from '../api/explore'

// 本地兜底映射
const CITY_IMAGE_MAP: Record<string, string> = {
  '北京': 'beijing.webp',
  '上海': 'shanghai.webp',
  '广州': 'guangzhou.webp',
  '深圳': 'shenzhen.webp',
  '成都': 'chengdu.webp',
  '杭州': 'hangzhou.webp',
  '西安': 'xian.webp',
  '重庆': 'chongqing.webp',
  '厦门': 'xiamen.webp',
  '大理': 'dali.webp',
  '丽江': 'lijiang.webp',
  '三亚': 'sanya.webp',
  '桂林': 'guilin.webp',
  '长沙': 'changsha.webp',
  '武汉': 'wuhan.webp',
  '南京': 'nanjing.webp',
  '青岛': 'qingdao.webp',
  '苏州': 'suzhou.webp',
  '昆明': 'kunming.webp',
  '哈尔滨': 'haerbin.webp',
}

const PLACEHOLDER = '/assets/city/placeholder.svg'

function getCityImage(city: CityCandidate): string {
  // 1. 后端 URL 优先
  if (city.image_url && city.image_url.trim()) {
    return city.image_url
  }
  // 2. 本地映射
  const filename = CITY_IMAGE_MAP[city.city]
  if (filename) {
    return `/assets/city/${filename}`
  }
  // 3. 占位图
  return PLACEHOLDER
}

interface CityCardProps {
  city: CityCandidate
  onClick: () => void
}

export default function CityCard({ city, onClick }: CityCardProps) {
  const [imgSrc, setImgSrc] = useState(() => getCityImage(city))
  const [imgError, setImgError] = useState(false)

  useEffect(() => {
    setImgSrc(getCityImage(city))
    setImgError(false)
  }, [city.city, city.image_url])

  const handleImgError = () => {
    if (!imgError) {
      setImgSrc(PLACEHOLDER)
      setImgError(true)
    }
  }

  const starScore = city.score / 2

  return (
    <div className="city-card" onClick={onClick}>
      <img
        className="city-card-img"
        src={imgSrc}
        alt={city.city}
        loading="lazy"
        onError={handleImgError}
      />
      <div className="city-card-body">
        <div className="city-card-name">{city.city}</div>

        <div className="city-card-score">
          <span className="score-stars">
            {'★'.repeat(Math.round(starScore))}
            {'☆'.repeat(5 - Math.round(starScore))}
          </span>
          <span className="score-num">{city.score.toFixed(1)}</span>
        </div>

        <div className="city-card-reason">{city.reason}</div>
        {city.intro && <div className="city-card-intro">{city.intro}</div>}

        {/* 标签 */}
        {city.tags && city.tags.length > 0 && (
          <div className="city-card-tags">
            {city.tags.map((tag) => (
              <span key={tag} className="city-tag">{tag}</span>
            ))}
          </div>
        )}

        {/* 日均花费 */}
        {city.daily_cost > 0 && (
          <div className="city-card-cost">¥{city.daily_cost}/天</div>
        )}
      </div>
    </div>
  )
}