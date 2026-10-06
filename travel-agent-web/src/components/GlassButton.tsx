/**
 * 玻璃态按钮组件
 * 
 * 参考 Log Out 按钮的磨砂玻璃风格
 * 半透明背景 + 模糊 + 边框高光
 * 
 * 可调参数见 CSS 变量
 */

import type { ReactNode } from 'react'

interface GlassButtonProps {
  children: ReactNode
  onClick?: () => void
  href?: string
  className?: string
}

export default function GlassButton({ children, onClick, href, className = '' }: GlassButtonProps) {
  const baseClass = 'glass-btn'

  if (href) {
    return (
      <a href={href} className={`${baseClass} ${className}`}>
        {children}
      </a>
    )
  }

  return (
    <button className={`${baseClass} ${className}`} onClick={onClick}>
      {children}
    </button>
  )
}
