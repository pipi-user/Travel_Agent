/**
 * 灵感探索页
 * 选择目的地城市，进入行程规划
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import WebGLBackground from '../components/WebGLBackground';

const POPULAR_CITIES = [
  '北京', '上海', '广州', '成都', '重庆', '杭州',
  '西安', '大理', '三亚', '厦门', '南京', '苏州',
];

export default function ExplorePage() {
  const [city, setCity] = useState('');
  const navigate = useNavigate();

  const handleSubmit = () => {
    if (city.trim()) {
      navigate(`/planner/${encodeURIComponent(city.trim())}`);
    }
  };

  return (
    <>
      <WebGLBackground />
      <Navbar currentPage="home" onNavigate={() => navigate('/')} />
      <main style={{
        position: 'relative', zIndex: 1,
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '120px 24px 60px',
      }}>
        <div style={{
          background: 'rgba(255,255,255,0.08)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(255,255,255,0.18)',
          borderRadius: '24px',
          padding: '48px',
          maxWidth: '600px',
          width: '100%',
          textAlign: 'center',
        }}>
          <h2 style={{
            fontFamily: 'var(--font-calligraphy)',
            fontSize: '48px',
            color: '#fff',
            marginBottom: '16px',
          }}>
            想去哪里？
          </h2>
          <p style={{
            color: 'rgba(255,255,255,0.6)',
            fontSize: '16px',
            marginBottom: '32px',
          }}>
            输入你心仪的目的地城市
          </p>

          <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
            <input
              type="text"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              placeholder="输入城市名称..."
              style={{
                flex: 1,
                padding: '14px 20px',
                borderRadius: '12px',
                border: '1px solid rgba(255,255,255,0.2)',
                background: 'rgba(255,255,255,0.1)',
                color: '#fff',
                fontSize: '16px',
                outline: 'none',
              }}
            />
            <button
              className="glass-btn"
              onClick={handleSubmit}
              style={{ padding: '14px 28px' }}
            >
              出发 →
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center' }}>
            {POPULAR_CITIES.map((c) => (
              <button
                key={c}
                onClick={() => setCity(c)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '20px',
                  border: '1px solid rgba(255,255,255,0.15)',
                  background: city === c ? 'rgba(212,175,55,0.2)' : 'transparent',
                  color: city === c ? '#d4af37' : 'rgba(255,255,255,0.6)',
                  cursor: 'pointer',
                  fontSize: '14px',
                  transition: 'all 0.2s',
                }}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      </main>
    </>
  );
}
