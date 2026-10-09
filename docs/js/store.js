// Everything here stays in this browser (localStorage). Nothing is uploaded.
function read(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key));
    return value ?? fallback;
  } catch {
    return fallback;
  }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

const HISTORY = "fluxvid.history", RECENT = "fluxvid.recent", PREFS = "fluxvid.prefs";

export const loadHistory = () => (Array.isArray(read(HISTORY, [])) ? read(HISTORY, []) : []);
export function addHistory(entry) {
  const list = [{ ...entry, at: Date.now() }, ...loadHistory()].slice(0, 30);
  write(HISTORY, list);
  return list;
}
export function clearHistory() { write(HISTORY, []); return []; }

export const loadRecent = () => (Array.isArray(read(RECENT, [])) ? read(RECENT, []) : []);
export function addRecent(url, title) {
  const list = [{ url, title }, ...loadRecent().filter((r) => r.url !== url)].slice(0, 6);
  write(RECENT, list);
  return list;
}
export function clearRecent() { write(RECENT, []); return []; }

// Remembered choices: last media type and the highest video height the user picked.
export const loadPrefs = () => ({ type: "video", height: null, ...read(PREFS, {}) });
export function savePrefs(patch) { write(PREFS, { ...loadPrefs(), ...patch }); }
