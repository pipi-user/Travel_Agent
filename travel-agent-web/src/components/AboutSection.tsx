/**
 * 关于页区块
 * 
 * 简洁的关于信息，深色背景
 */

export default function AboutSection() {
  return (
    <section id="section-about" className="about-section">
      <div className="about-content">
        <h2 className="about-title">关于 Travel Agent</h2>
        <p className="about-desc">
          Travel Agent 是一个基于 AI 的智能旅行规划系统。<br />
          融合 LangGraph 决策流水线与向量记忆系统，<br />
          让每一次旅行规划都成为一次个性化的智能对话。
        </p>
        <div className="about-tech">
          <div className="tech-item">
            <span className="tech-icon">🧠</span>
            <span className="tech-label">LangGraph</span>
          </div>
          <div className="tech-item">
            <span className="tech-icon">🔍</span>
            <span className="tech-label">向量记忆</span>
          </div>
          <div className="tech-item">
            <span className="tech-icon">⚡</span>
            <span className="tech-label">FastAPI</span>
          </div>
          <div className="tech-item">
            <span className="tech-icon">🎨</span>
            <span className="tech-label">React + WebGL</span>
          </div>
        </div>
        <p className="about-footer">© 2026 Travel Agent. All rights reserved.</p>
      </div>
    </section>
  )
}
