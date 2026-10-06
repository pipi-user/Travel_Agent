/**
 * 极简顶栏
 */

interface SimpleHeaderProps {
  title?: string
  right?: React.ReactNode
}

export default function SimpleHeader({ title, right }: SimpleHeaderProps) {
  return (
    <header className="simple-header">
      <div className="header-logo">
        Travel<span>Agent</span>
      </div>
      {title && <span style={{ fontSize: 14, color: '#8a8580' }}>{title}</span>}
      <div className="header-actions">
        {right}
      </div>
    </header>
  )
}
