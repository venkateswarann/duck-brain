export const API_BASE = import.meta.env.VITE_API_BASE ?? "";
export const WS_BASE =
  import.meta.env.VITE_WS_URL ??
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;

export function apiUrl(path: string) {
  return `${API_BASE}${path}`;
}

export function wsUrl(path: string) {
  // When using Vite proxy, connect to same host
  if (!import.meta.env.VITE_WS_URL) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}${path}`;
  }
  return `${import.meta.env.VITE_WS_URL}${path}`;
}
