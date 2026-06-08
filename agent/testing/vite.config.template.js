/**
 * UIForge-Agent 通用 Vitest 配置片段（已合并进 templates/vite.config.js.j2）。
 * 生成项目的 vite.config.js 应包含同等 test 段。
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
    include: ['tests/**/*.{test,spec}.{js,jsx}'],
    pool: 'forks',
    poolOptions: { forks: { singleFork: true } },
  },
});
