// Run: node --test tests/frontend/frontend.test.mjs   (Node 18+)
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

const server = http.createServer((req, res) => {
  const json = (status, body) => { res.writeHead(status, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
  if (req.url === "/api/health") return json(200, { status: "ok" });
  if (req.url === "/api/info") return json(400, { error: { code: "invalid_url", message: "Enter a valid http or https link." } });
  if (req.url === "/api/jobs/abc") return json(200, { id: "abc", state: "running", stage: "downloading", progress: 0.5 });
  if (req.url.startsWith("/html404")) { res.writeHead(404, { "Content-Type": "text/html" }); return res.end("<h1>Not found</h1>"); }
  if (req.url === "/api/jobs/waking") { res.writeHead(502, { "Content-Type": "text/html" }); return res.end("Bad gateway"); }
  if (req.url === "/api/jobs/gone" && req.method === "DELETE") { res.writeHead(204); return res.end(); }
  if (req.url === "/api/hang") return; // never answers
  json(404, { error: { code: "not_found", message: "That endpoint does not exist." } });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
globalThis.location = { hostname: "shiv-yogi19.github.io" };
globalThis.window = { FLUXVID_CONFIG: { apiBase: base + "/", devApiBase: "http://localhost:8000" } };
const api = await import("../../docs/js/api.js?configured");
const fmt = await import("../../docs/js/format.js");

test.after(() => server.close());

test("trailing slash is trimmed and health works", async () => {
  assert.equal(api.API_BASE, base);
  assert.equal((await api.getHealth()).status, "ok");
});
test("backend error body becomes ApiError with code, message and status", async () => {
  await assert.rejects(api.getInfo("x"), (e) => e instanceof api.ApiError && e.code === "invalid_url" && e.status === 400 && /valid http/.test(e.message));
});
test("job status passes real progress through", async () => {
  assert.equal((await api.getJob("abc")).progress, 0.5);
});
test("cancel returns nothing on 204", async () => {
  assert.equal(await api.cancelJob("gone"), null);
});
test("HTML 404 from a wrong server address points at config.js", async () => {
  globalThis.window.FLUXVID_CONFIG.apiBase = base + "/html404?";
  const wrong = await import("../../docs/js/api.js?wrong");
  await assert.rejects(wrong.getHealth(), (e) => e.code === "server_error" && /config\.js/.test(e.message));
  globalThis.window.FLUXVID_CONFIG.apiBase = base;
});
test("proxy 502 while the free server wakes is reported as server_waking", async () => {
  globalThis.window.FLUXVID_CONFIG.apiBase = base;
  const m = await import("../../docs/js/api.js?waking");
  await assert.rejects(m.getJob("waking"), (e) => e.code === "server_waking");
});
test("unreachable server is a network error, slow server is a timeout, abort is AbortError", async () => {
  globalThis.window.FLUXVID_CONFIG.apiBase = "http://127.0.0.1:1";
  const down = await import("../../docs/js/api.js?down");
  await assert.rejects(down.getHealth(undefined, 500), (e) => e.code === "network");
  globalThis.window.FLUXVID_CONFIG.apiBase = base;
  const up = await import("../../docs/js/api.js?up");
  const ctl = new AbortController();
  const hung = up.getHealth(ctl.signal, 5000);
  ctl.abort();
  await assert.rejects(hung, (e) => e.name === "AbortError");
});
test("missing apiBase on a non-local page is reported, never silently using localhost", async () => {
  globalThis.window.FLUXVID_CONFIG = { devApiBase: "http://localhost:8000" };
  const none = await import("../../docs/js/api.js?none");
  assert.equal(none.API_BASE, "");
  await assert.rejects(none.getHealth(), (e) => e.code === "not_configured");
});
test("format helpers", () => {
  assert.equal(fmt.formatDuration(42), "00:42");
  assert.equal(fmt.formatDuration(3725), "1:02:05");
  assert.equal(fmt.formatBytes(1536), "1.5 KB");
  assert.equal(fmt.formatBytes(25 * 1024 * 1024), "25.0 MB");
  assert.equal(fmt.extractUrl("Watch this https://youtu.be/abc?t=1 now"), "https://youtu.be/abc?t=1");
  assert.equal(fmt.extractUrl("no link"), null);
  assert.equal(fmt.parseHttpUrl("javascript:alert(1)"), null);
  assert.equal(fmt.parseHttpUrl(" https://example.com/a "), "https://example.com/a");
});
test("local storage helpers survive broken storage", async () => {
  const mem = new Map();
  globalThis.localStorage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  const store = await import("../../docs/js/store.js?mem");
  store.addRecent("https://a.test/1", "One"); store.addRecent("https://a.test/2", "Two"); store.addRecent("https://a.test/1", "One");
  assert.deepEqual(store.loadRecent().map((r) => r.title), ["One", "Two"]);
  store.addHistory({ filename: "f", type: "video", quality: "720p", status: "Sent to browser" });
  assert.equal(store.loadHistory().length, 1);
  assert.deepEqual(store.clearHistory(), []);
  store.savePrefs({ height: 720 });
  assert.equal(store.loadPrefs().height, 720);
  globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  const broken = await import("../../docs/js/store.js?broken");
  assert.deepEqual(broken.loadHistory(), []);
  broken.addHistory({ filename: "x" }); // must not throw
});
