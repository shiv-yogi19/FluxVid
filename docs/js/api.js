const cfg = window.FLUXVID_CONFIG || {};
const isLocalPage = ["localhost", "127.0.0.1"].includes(location.hostname);
export const API_BASE = String(cfg.apiBase || (isLocalPage ? cfg.devApiBase : "") || "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const sleepFor = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  });
export const sleep = sleepFor;

async function parse(res) {
  if (res.status === 204) return null;
  const isJson = (res.headers.get("Content-Type") || "").includes("json");
  const data = isJson ? await res.json().catch(() => null) : null;
  if (res.ok) return data;
  if (data?.error) throw new ApiError(data.error.code, data.error.message, res.status);
  if (res.status >= 502 && res.status <= 504) {
    throw new ApiError("server_waking", "The server is starting up. Wait a few seconds and try again.", res.status);
  }
  throw new ApiError("server_error",
    `The server returned an unexpected response (HTTP ${res.status}). Check that the server address in config.js is correct.`, res.status);
}

async function request(method, path, { body, signal, timeoutMs = 30000, retries = 0 } = {}) {
  if (!API_BASE) throw new ApiError("not_configured", "The server address is not set. Edit config.js and set apiBase.");
  for (let attempt = 0; ; attempt++) {
    const ctl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, timeoutMs);
    const relay = () => ctl.abort();
    signal?.addEventListener("abort", relay, { once: true });
    if (signal?.aborted) ctl.abort();
    try {
      const res = await fetch(API_BASE + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: ctl.signal,
      });
      return await parse(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      if (attempt < retries) { await sleepFor(1500, signal); continue; }
      throw timedOut
        ? new ApiError("timeout", "The server took too long to answer. Try again.")
        : new ApiError("network", "Could not reach the FluxVid server. Check your connection and try again.");
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", relay);
    }
  }
}

export const getHealth = (signal, timeoutMs = 10000) => request("GET", "/api/health", { signal, timeoutMs });
export const getInfo = (url, signal) => request("POST", "/api/info", { body: { url }, signal, timeoutMs: 100000 });
export const createJob = (job, signal) => request("POST", "/api/jobs", { body: job, signal });
export const getJob = (id, signal) => request("GET", `/api/jobs/${encodeURIComponent(id)}`, { signal, timeoutMs: 15000 });
export const cancelJob = (id) => request("DELETE", `/api/jobs/${encodeURIComponent(id)}`, { timeoutMs: 10000 });
export const fileUrl = (path) => API_BASE + path;

// Free hosting sleeps when idle; keep asking /api/health until the server answers.
export async function waitForServer({ signal, maxMs = 90000, onTick } = {}) {
  const started = Date.now();
  for (;;) {
    try {
      return await getHealth(signal, 10000);
    } catch (err) {
      if (err.name === "AbortError" || err.code === "not_configured") throw err;
      if (Date.now() - started > maxMs) throw err;
      onTick?.(Math.round((Date.now() - started) / 1000));
      await sleepFor(3000, signal);
    }
  }
}
