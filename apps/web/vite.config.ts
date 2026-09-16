import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5288, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8188' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
})
