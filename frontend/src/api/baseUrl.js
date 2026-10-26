// Public deployments may proxy the API under the same origin. A separate API
// origin must be supplied explicitly when building the frontend.
const configured = import.meta.env.VITE_API_BASE_URL?.trim();
const fallback = import.meta.env.PROD ? window.location.origin : 'http://127.0.0.1:8000';
const url = new URL(configured || fallback);

if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password
  || url.pathname !== '/' || url.search || url.hash) {
  throw new Error('VITE_API_BASE_URL must be an HTTP(S) origin without a path.');
}
if (window.location.protocol === 'https:' && url.protocol !== 'https:') {
  throw new Error('A secure page requires an HTTPS room API.');
}

export const API_BASE_URL = url.origin;
