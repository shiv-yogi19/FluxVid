const BASE = (window.FLUXVID_API || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

async function post(path, body, signal) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("network", "Could not reach the FluxVid server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = {};
    try {
      detail = (await res.json()).error || {};
    } catch { /* non-JSON error body */ }
    throw new ApiError(detail.code || "server_error", detail.message || "The server could not complete this request.");
  }
  return res;
}

export async function getInfo(url, signal) {
  return (await post("/api/info", { url }, signal)).json();
}

function filenameFrom(header) {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try { return decodeURIComponent(star[1]); } catch { /* fall through */ }
  }
  const plain = /filename="([^"]+)"/i.exec(header);
  return plain ? plain[1] : null;
}

// Resolves once the whole file has been received. onReady fires when the
// server starts sending bytes; onProgress receives 0..1, or null if unknown.
export async function downloadMedia(request, { signal, onReady, onProgress }) {
  const res = await post("/api/download", request, signal);
  onReady();
  const total = Number(res.headers.get("Content-Length")) || 0;
  const type = res.headers.get("Content-Type") || "application/octet-stream";
  const filename = filenameFrom(res.headers.get("Content-Disposition")) || "download_FluxVid-created by shiv yogi";
  if (!res.body) return { blob: await res.blob(), filename };

  const reader = res.body.getReader();
  const chunks = [];
  let loaded = 0;
  onProgress(total ? 0 : null);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    onProgress(total ? Math.min(loaded / total, 1) : null);
  }
  return { blob: new Blob(chunks, { type }), filename };
}
