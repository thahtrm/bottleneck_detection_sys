import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': apiProxy,
      '/webhooks': apiProxy,
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
