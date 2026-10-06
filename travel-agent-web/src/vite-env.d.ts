/// <reference types="vite/client" />

declare module '@amap/amap-jsapi-loader' {
  const AMapLoader: {
    load(config: { key: string; version: string; plugins?: string[] }): Promise<any>
  }
  export default AMapLoader
}