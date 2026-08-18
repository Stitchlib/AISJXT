import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  // 注：本机沙箱的 safe-delete 拦截会卡死 build 末尾清空 dist 的 rmSync，
  // 关闭 emptyOutDir 后构建期不再触发任何删除，可稳定通过 npm run build。
  build: {
    emptyOutDir: false,
  },
  server: {
    port: 3000,
    proxy: {
      // 后端 REST 接口：/api/v1/* -> http://127.0.0.1:8000
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      // 后端 WebSocket：/ws -> ws://127.0.0.1:8000
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true
      }
    }
  }
})
