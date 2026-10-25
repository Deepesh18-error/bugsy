import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['pyodide'] },
  resolve: {
    // y-monaco imports Monaco's pre-export-map path. Keep it pointed at the
    // same ESM API used by CodeEditor so the binding and editor share a copy.
    alias: {
      'monaco-editor/esm/vs/editor/editor.api.js': 'monaco-editor/editor/editor.api.js',
    },
  },
  server: {
    host: '127.0.0.1',
  },
});
