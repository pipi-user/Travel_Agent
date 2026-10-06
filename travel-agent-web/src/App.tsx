/**
 * Travel Agent 主应用
 * 
 * 首页：单页纵向滚动布局 Hero → 介绍 → 关于
 * 子页面：灵感漫游 / 定向定制 / 行程规划
 * 顶部导航随滚动自动高亮
 * WebGL 液态玻璃背景
 */

import { useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom'
import Navbar from './components/Navbar'
import HeroSection from './components/HeroSection'
import IntroSection from './components/IntroSection'
import AboutSection from './components/AboutSection'
import WebGLBackground from './components/WebGLBackground'
import ExplorePage from './pages/ExplorePage'
import TargetChatPage from './pages/TargetChatPage'
import PlannerPage from './pages/PlannerPage'
import InspireChatPage from './pages/InspireChatPage'
import WorkshopPage from './pages/WorkshopPage'
import RoutePage from './pages/RoutePage'
import './App.css'

type NavPage = 'home' | 'intro' | 'about'

function HomePage() {
  const [currentPage, setCurrentPage] = useState<NavPage>('home')

  const handleNavigate = useCallback((page: NavPage) => {
    setCurrentPage(page)
  }, [])

  const handleExplore = useCallback(() => {
    const el = document.getElementById('section-intro')
    if (el) el.scrollIntoView({ behavior: 'smooth' })
  }, [])

  const handleCurate = useCallback(() => {
    const el = document.getElementById('section-intro')
    if (el) el.scrollIntoView({ behavior: 'smooth' })
  }, [])

  return (
    <>
      <WebGLBackground />
      <Navbar currentPage={currentPage} onNavigate={handleNavigate} />
      <main className="app-main">
        <HeroSection onExplore={handleExplore} />
        <IntroSection onExplore={handleExplore} onCurate={handleCurate} />
        <AboutSection />
      </main>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}

function AppRoutes() {
  const location = useLocation()
  return (
    <div className="app">
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/target" element={<div className="inspiration-theme"><TargetChatPage key={location.key} /></div>} />
        <Route path="/planner/:city" element={<PlannerPage />} />
        <Route path="/inspire" element={<div className="inspiration-theme"><InspireChatPage key={location.key} /></div>} />
        <Route path="/workshop/:city" element={<div className="inspiration-theme"><WorkshopPage /></div>} />
        <Route path="/route-result/:city" element={<div className="inspiration-theme"><RoutePage /></div>} />
      </Routes>
    </div>
  )
}
