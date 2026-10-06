/**
 * WebGL 液态玻璃背景
 * 
 * 使用原生 WebGL 实现全屏液态玻璃折射效果
 * 鼠标移动产生柔和的扭曲变形
 * 
 * 可调参数:
 * - DISTORTION_STRENGTH: 扭曲强度 (默认 0.04)
 * - MOUSE_INFLUENCE: 鼠标影响范围 (默认 0.35)
 * - FLOW_SPEED: 流动速度 (默认 0.2)
 * - NOISE_SCALE: 噪声缩放 (默认 2.5)
 */

import { useEffect, useRef } from 'react'

/* ==================== 可调参数 ==================== */
const DISTORTION_STRENGTH = 0.04   // 扭曲强度，越大变形越明显
const MOUSE_INFLUENCE = 0.35       // 鼠标影响半径 (0~1)
const FLOW_SPEED = 0.2             // 流动速度
const NOISE_SCALE = 2.5            // 噪声缩放，越小纹理越大
const MOUSE_STRENGTH = 0.06        // 鼠标推拉强度
/* ================================================== */

// 顶点着色器 - 全屏四边形
const VERTEX_SHADER = `
  attribute vec2 a_position;
  varying vec2 v_uv;
  void main() {
    v_uv = a_position * 0.5 + 0.5;
    gl_Position = vec4(a_position, 0.0, 1.0);
  }
`

// 片段着色器 - 液态玻璃效果
const FRAGMENT_SHADER = `
  precision highp float;
  varying vec2 v_uv;
  uniform float u_time;
  uniform vec2 u_mouse;
  uniform vec2 u_resolution;

  const float DISTORTION = ${DISTORTION_STRENGTH};
  const float MOUSE_RADIUS = ${MOUSE_INFLUENCE};
  const float SPEED = ${FLOW_SPEED};
  const float NOISE_SCALE = ${NOISE_SCALE};
  const float MOUSE_STR = ${MOUSE_STRENGTH};

  // Simplex 噪声
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

  float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                       -0.577350269189626, 0.024390243902439);
    vec2 i  = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289(i);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                           + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy),
                            dot(x12.zw, x12.zw)), 0.0);
    m = m * m; m = m * m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
  }

  void main() {
    vec2 uv = v_uv;
    float aspect = u_resolution.x / u_resolution.y;
    vec2 uvAspect = vec2(uv.x * aspect, uv.y);

    // 鼠标归一化坐标
    vec2 mouseNorm = u_mouse / u_resolution;
    vec2 mouseAspect = vec2(mouseNorm.x * aspect, mouseNorm.y);

    // 基础流动噪声 - 多层叠加
    float t = u_time * SPEED;
    vec2 nUV = uv * NOISE_SCALE;

    float n1 = snoise(nUV + vec2(t * 0.3, t * 0.2));
    float n2 = snoise(nUV * 1.7 + vec2(-t * 0.25, t * 0.35));
    float n3 = snoise(nUV * 0.8 + vec2(t * 0.15, -t * 0.2));

    // 鼠标影响 - 计算到鼠标的距离
    float mouseDist = length(uvAspect - mouseAspect);
    float mouseEffect = smoothstep(MOUSE_RADIUS, 0.0, mouseDist);

    // 鼠标方向向量
    vec2 mouseDir = normalize(uvAspect - mouseAspect + 0.001);

    // 综合扭曲偏移 - 噪声 + 鼠标推拉
    vec2 distortion = vec2(
      n1 * DISTORTION + mouseEffect * mouseDir.x * MOUSE_STR,
      n2 * DISTORTION + mouseEffect * mouseDir.y * MOUSE_STR
    );

    vec2 distortedUV = uv + distortion;

    // 玻璃折射色散 - RGB 轻微分离
    float r = snoise(distortedUV * 10.0 + vec2(t * 0.12, 0.0));
    float g = snoise(distortedUV * 10.0 + vec2(0.0, t * 0.12));
    float b = snoise(distortedUV * 10.0 - vec2(t * 0.06, t * 0.06));

    // 基础底色 - 深蓝灰渐变
    vec3 baseColor = mix(
      vec3(0.04, 0.06, 0.12),
      vec3(0.08, 0.10, 0.18),
      uv.y
    );

    // 玻璃高光 - 基于噪声
    float highlight = smoothstep(0.35, 0.65, r * 0.5 + 0.5) * 0.12;
    float highlight2 = smoothstep(0.3, 0.7, n3 * 0.5 + 0.5) * 0.08;

    // 鼠标处光晕
    float mouseGlow = mouseEffect * 0.1;
    vec3 mouseColor = vec3(0.3, 0.5, 0.8) * mouseGlow;

    // 合成最终颜色
    vec3 color = baseColor
      + vec3(highlight, highlight * 0.9, highlight * 1.1)
      + highlight2 * vec3(0.8, 0.9, 1.0)
      + mouseColor;

    gl_FragColor = vec4(color, 1.0);
  }
`

export default function WebGLBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const mouseRef = useRef({ x: 0, y: 0 })
  const targetMouseRef = useRef({ x: 0, y: 0 })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const gl = canvas.getContext('webgl', { alpha: false, antialias: true })
    if (!gl) return

    // 编译着色器
    const compileShader = (source: string, type: number) => {
      const shader = gl.createShader(type)!
      gl.shaderSource(shader, source)
      gl.compileShader(shader)
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error('Shader compile error:', gl.getShaderInfoLog(shader))
        gl.deleteShader(shader)
        return null
      }
      return shader
    }

    const vs = compileShader(VERTEX_SHADER, gl.VERTEX_SHADER)
    const fs = compileShader(FRAGMENT_SHADER, gl.FRAGMENT_SHADER)
    if (!vs || !fs) return

    const program = gl.createProgram()!
    gl.attachShader(program, vs)
    gl.attachShader(program, fs)
    gl.linkProgram(program)

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('Program link error:', gl.getProgramInfoLog(program))
      return
    }

    gl.useProgram(program)

    // 全屏四边形顶点
    const vertices = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1])
    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW)

    const posLoc = gl.getAttribLocation(program, 'a_position')
    gl.enableVertexAttribArray(posLoc)
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0)

    // Uniform 位置
    const uTime = gl.getUniformLocation(program, 'u_time')
    const uMouse = gl.getUniformLocation(program, 'u_mouse')
    const uResolution = gl.getUniformLocation(program, 'u_resolution')

    // 鼠标追踪 - 使用目标位置实现平滑插值
    const handleMouse = (e: MouseEvent) => {
      targetMouseRef.current = { x: e.clientX, y: canvas.height - e.clientY }
    }
    window.addEventListener('mousemove', handleMouse)

    // 尺寸调整
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio, 2)
      canvas.width = window.innerWidth * dpr
      canvas.height = window.innerHeight * dpr
      canvas.style.width = window.innerWidth + 'px'
      canvas.style.height = window.innerHeight + 'px'
      gl.viewport(0, 0, canvas.width, canvas.height)
    }
    resize()
    window.addEventListener('resize', resize)

    // 渲染循环
    let frameId: number
    const startTime = performance.now()

    const render = () => {
      // 平滑插值鼠标位置 (lerp)
      mouseRef.current.x += (targetMouseRef.current.x - mouseRef.current.x) * 0.08
      mouseRef.current.y += (targetMouseRef.current.y - mouseRef.current.y) * 0.08

      gl.uniform1f(uTime, (performance.now() - startTime) / 1000)
      gl.uniform2f(uMouse, mouseRef.current.x, mouseRef.current.y)
      gl.uniform2f(uResolution, canvas.width, canvas.height)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      frameId = requestAnimationFrame(render)
    }
    render()

    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('mousemove', handleMouse)
      window.removeEventListener('resize', resize)
      gl.deleteProgram(program)
      gl.deleteShader(vs)
      gl.deleteShader(fs)
      gl.deleteBuffer(buffer)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'none',
      }}
    />
  )
}
