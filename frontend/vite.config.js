import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig(({ command }) => ({
  plugins: [react()],
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['pyodide'] },
  resolve: {
    // y-monaco imports Monaco's pre-export-map path. Keep it pointed at the
    // same ESM API used by CodeEditor so the binding and editor share a copy.
    alias: {
      '#feedback-worker': fileURLToPath(new URL(command === 'build'
        ? './src/workers/disabledFeedbackWorker.js'
        : './src/workers/createFeedbackWorker.js', import.meta.url)),
      'monaco-editor/esm/vs/editor/editor.api.js': 'monaco-editor/editor/editor.api.js',
    },
  },
  server: {
    host: '127.0.0.1',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.jsx'],
  },
}));
