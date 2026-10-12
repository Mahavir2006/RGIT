import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

// The console is built straight into public/ so scripts/server.mjs can serve it as a plain
// static bundle under the same origin as the WebGL site. No dev proxy and no runtime CDN.
export default defineConfig({
  root: import.meta.dirname,
  base: '/assets/sentinel/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') }
  },
  build: {
    outDir: '../../public/assets/sentinel',
    emptyOutDir: true,
    target: 'es2022',
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          motion: ['framer-motion', 'gsap'],
          react: ['react', 'react-dom', 'react-router-dom']
        }
      }
    }
  },
  server: { port: 4300 }
});