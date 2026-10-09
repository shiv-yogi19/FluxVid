const KEY = "fluxvid.history";
const LIMIT = 30;

export function loadHistory() {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function save(list) {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch { /* storage unavailable */ }
}

export function addHistory(entry) {
  const list = [{ ...entry, at: Date.now() }, ...loadHistory()].slice(0, LIMIT);
  save(list);
  return list;
}

export function clearHistory() {
  save([]);
  return [];
}
