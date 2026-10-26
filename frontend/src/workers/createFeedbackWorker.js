/** Development-only factory; excluded entirely from public builds. */
export default function createFeedbackWorker() {
  return new Worker(new URL('./pythonFeedback.worker.js', import.meta.url), { type: 'module' });
}
