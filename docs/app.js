import { hydrateIcons, setIcon, icon } from "./js/icons.js";
import { API_BASE, ApiError, cancelJob, createJob, fileUrl, getInfo, getJob, sleep, waitForServer, getHealth } from "./js/api.js";
import { addHistory, addRecent, clearHistory, clearRecent, loadHistory, loadPrefs, loadRecent, savePrefs } from "./js/store.js";
import { extractUrl, formatBytes, formatDuration, parseHttpUrl } from "./js/format.js";

const $ = (sel, root = document) => root.querySelector(sel);
const slot = (root, name) => root.querySelector(`[data-slot="${name}"]`);

const els = {
  form: $("#urlForm"), input: $("#urlInput"), hint: $("#urlHint"), clearInput: $("#clearInput"),
  paste: $("#pasteBtn"), analyze: $("#analyzeBtn"), stage: $("#stage"),
  status: $("#status"), statusText: $("#statusText"),
  recent: $("#recent"), recentList: $("#recentList"),
  historyBtn: $("#historyBtn"), history: $("#history"), historyList: $("#historyList"), historyEmpty: $("#historyEmpty"),
};
const state = { info: null, url: "", type: "video", quality: null, server: "connecting", job: null, serverCtl: null };
let ui = null; // references into the rendered media card

// ---------- intro ----------
function startIntro() {
  const intro = $("#intro");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    document.body.classList.add("ready");
    setTimeout(() => intro.remove(), reduce ? 0 : 900);
  };
  if (reduce) return finish();
  const timer = setTimeout(finish, 4400);
  intro.addEventListener("click", () => { clearTimeout(timer); intro.classList.add("skip"); finish(); });
}

// ---------- server status (free hosting sleeps when idle) ----------
const STATUS_TEXT = { connecting: "Connecting", waking: "Waking server", online: "Online", offline: "Offline - tap to retry" };

function setServer(next) {
  state.server = next;
  els.status.dataset.state = next;
  els.statusText.textContent = STATUS_TEXT[next];
}

async function connectServer() {
  state.serverCtl?.abort();
  const ctl = (state.serverCtl = new AbortController());
  setServer("connecting");
  try {
    await getHealth(ctl.signal, 8000);
    setServer("online");
    return true;
  } catch (err) {
    if (err.name === "AbortError") return false;
    if (err.code === "not_configured") { setServer("offline"); return false; }
  }
  setServer("waking");
  try {
    await waitForServer({ signal: ctl.signal });
    setServer("online");
    return true;
  } catch (err) {
    if (err.name !== "AbortError") setServer("offline");
    return false;
  }
}

els.status.addEventListener("click", () => { if (state.server === "offline") connectServer(); });

// ---------- helpers ----------
function showStage(node) {
  els.stage.replaceChildren(node);
  hydrateIcons(els.stage);
}

function arrowNavigation(group) {
  group.addEventListener("keydown", (e) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    const items = [...group.querySelectorAll('[role="radio"]:not(:disabled)')];
    const next = items[(items.indexOf(document.activeElement) + keys[e.key] + items.length) % items.length];
    if (next) { e.preventDefault(); next.focus(); next.click(); }
  });
}

function syncRadios(group, isSelected) {
  for (const b of group.querySelectorAll('[role="radio"]')) {
    const selected = isSelected(b);
    b.setAttribute("aria-checked", String(selected));
    b.tabIndex = selected ? 0 : -1;
  }
}

// ---------- URL field, paste, share ----------
function syncClear() { els.clearInput.hidden = !els.input.value; }

async function pasteFromClipboard() {
  const iconEl = $(".ico", els.paste), label = $(".lbl", els.paste);
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) throw new Error("empty");
    els.input.value = text;
    syncClear();
    els.hint.textContent = "";
    setIcon(iconEl, "check");
    label.textContent = "Pasted";
    setTimeout(() => { setIcon(iconEl, "paste"); label.textContent = "Paste"; }, 1600);
    if (parseHttpUrl(text)) analyze();
  } catch {
    els.input.focus();
    els.hint.textContent = "Clipboard access is blocked. Press and hold the field to paste.";
  }
}

function handleSharedLink() {
  const p = new URLSearchParams(location.search);
  const link = extractUrl([p.get("url"), p.get("text"), p.get("title")].filter(Boolean).join(" "));
  if (!link) return;
  history.replaceState(null, "", location.pathname);
  els.input.value = link;
  syncClear();
  analyze();
}

// ---------- analyze ----------
let analyzeCtl = null;

async function analyze(urlOverride) {
  if (typeof urlOverride === "string") { els.input.value = urlOverride; syncClear(); }
  const url = parseHttpUrl(els.input.value);
  if (!url) {
    els.hint.textContent = "Enter a valid link that starts with http or https.";
    els.input.focus();
    return;
  }
  els.hint.textContent = "";
  cancelActiveJob();
  analyzeCtl?.abort();
  const ctl = (analyzeCtl = new AbortController());
  const loading = $("#tpl-loading").content.cloneNode(true);
  showStage(loading);
  els.analyze.disabled = true;
  try {
    if (state.server !== "online") {
      slot(els.stage, "text").textContent = "Waking the server. Free hosting sleeps when idle, so this can take up to a minute.";
      if (!(await connectServer())) throw new ApiError("network", "Could not reach the FluxVid server. Check your connection and try again.");
      slot(els.stage, "text").textContent = "Reading details from the source.";
    }
    const info = await getInfo(url, ctl.signal);
    const prefs = loadPrefs();
    Object.assign(state, { info, url, type: info.types.includes(prefs.type) ? prefs.type : info.types[0] });
    renderRecent(addRecent(url, info.title));
    renderMedia();
  } catch (err) {
    if (err.name !== "AbortError") renderError(err);
  } finally {
    if (analyzeCtl === ctl) els.analyze.disabled = false;
  }
}

function renderError(err) {
  const node = $("#tpl-error").content.cloneNode(true);
  slot(node, "text").textContent =
    err.message || "The source may be unsupported, private, DRM-protected, restricted, or temporarily unavailable.";
  slot(node, "retry").addEventListener("click", () => analyze());
  showStage(node);
}

// ---------- media card ----------
function renderMedia() {
  const { info } = state;
  const node = $("#tpl-media").content.cloneNode(true);
  const root = $(".media", node);
  const s = (name) => slot(root, name);

  s("title").textContent = info.title;
  s("found").textContent = info.types.length === 2 ? "Video and audio found" : info.types[0] === "video" ? "Video found" : "Audio found";
  setIcon(s("foundIcon"), info.types[0]);
  if (info.duration) s("duration").textContent = formatDuration(info.duration); else s("durationChip").hidden = true;
  if (info.platform) s("platform").textContent = info.platform; else s("platformChip").hidden = true;
  s("best").textContent = info.video.length ? `Up to ${info.video[0].label}` : "Audio only";

  const thumb = s("thumb");
  if (info.thumbnail) {
    const img = new Image();
    Object.assign(img, { src: info.thumbnail, alt: "", loading: "lazy", referrerPolicy: "no-referrer" });
    thumb.prepend(img);
  }
  if (info.source_url) thumb.href = info.source_url; else thumb.removeAttribute("href");

  ui = {
    root, seg: s("seg"), qualities: s("qualities"), output: s("output"), btn: s("btn"), icon: s("dlIcon"), label: s("dlLabel"),
    box: s("progressBox"), bar: s("bar"), text: s("progressText"), cancel: s("cancel"),
    error: s("error"), errorText: s("errorText"), done: s("done"), doneName: s("doneName"), saveAgain: s("saveAgain"),
  };
  for (const b of ui.seg.querySelectorAll("button")) {
    b.disabled = !info.types.includes(b.dataset.type);
    b.addEventListener("click", () => selectType(b.dataset.type));
  }
  arrowNavigation(ui.seg);
  arrowNavigation(ui.qualities);
  ui.btn.addEventListener("click", startDownload);
  ui.cancel.addEventListener("click", cancelActiveJob);
  slot(ui.error, "retry").addEventListener("click", startDownload);
  s("back").addEventListener("click", reset);

  showStage(node);
  selectType(state.type);
}

function initialQuality(options, type) {
  const usable = options.filter((o) => !o.over_limit);
  if (!usable.length) return options[0].id;
  const height = loadPrefs().height;
  if (type === "video" && height) {
    const fit = usable.find((o) => Number(o.id) <= height);   // options are sorted high to low
    if (fit) return fit.id;
  }
  return (usable.find((o) => o.recommended) || usable[0]).id;
}

function selectType(type) {
  state.type = type;
  savePrefs({ type });
  ui.seg.dataset.value = type;
  syncRadios(ui.seg, (b) => b.dataset.type === type);
  const options = state.info[type];
  state.quality = initialQuality(options, type);
  ui.qualities.replaceChildren(...options.map((opt) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "q";
    b.setAttribute("role", "radio");
    b.dataset.id = opt.id;
    b.disabled = opt.over_limit;
    const name = document.createElement("span");
    name.className = "q-name";
    name.textContent = opt.label;
    b.append(name);
    const sub = [];
    if (opt.size) sub.push(`about ${formatBytes(opt.size)}`);
    if (opt.over_limit) sub.push("over server limit");
    if (sub.length) {
      const small = document.createElement("span");
      small.className = "q-sub";
      small.textContent = sub.join(" - ");
      b.append(small);
    }
    if (opt.recommended && !opt.over_limit) {
      const tag = document.createElement("span");
      tag.className = "q-tag";
      tag.textContent = "Recommended";
      b.append(tag);
    }
    b.addEventListener("click", () => selectQuality(opt.id));
    return b;
  }));
  ui.output.textContent = `Saved as ${state.info[type + "_format"]}. Sizes are estimates and appear only when the source reports them.`;
  syncRadios(ui.qualities, (b) => b.dataset.id === state.quality);
  resetDownloadUi();
}

function selectQuality(id) {
  state.quality = id;
  if (state.type === "video" && /^\d+$/.test(id)) savePrefs({ height: Number(id) });
  syncRadios(ui.qualities, (b) => b.dataset.id === id);
  resetDownloadUi();
}

const qualityLabel = () => state.info[state.type].find((o) => o.id === state.quality)?.label ?? state.quality;

// ---------- download ----------
const BUTTON = {
  idle: ["download", "Download"],
  preparing: ["spinner", "Preparing..."],
  downloading: ["spinner", "Downloading"],
  processing: ["spinner", "Processing..."],
  done: ["check", "Ready"],
};

function setButton(name, suffix = "") {
  const [iconName, text] = BUTTON[name];
  ui.btn.dataset.state = name;
  if (ui.icon.dataset.icon !== iconName) setIcon(ui.icon, iconName);
  const busy = ["preparing", "downloading", "processing"].includes(name);
  ui.icon.classList.toggle("spin", busy);
  ui.icon.classList.toggle("draw", name === "done");
  ui.label.textContent = text + suffix;
  ui.btn.disabled = busy;
  ui.btn.setAttribute("aria-busy", String(busy));
  ui.seg.classList.toggle("locked", busy);
  ui.qualities.classList.toggle("locked", busy);
}

function resetDownloadUi() {
  if (!ui || state.job) return;
  setButton("idle");
  ui.box.hidden = ui.error.hidden = ui.done.hidden = true;
}

function showProgress(job) {
  ui.box.hidden = false;
  const known = typeof job.progress === "number";
  ui.bar.classList.toggle("indet", !known);
  if (known) {
    ui.bar.style.setProperty("--p", job.progress.toFixed(3));
    ui.bar.setAttribute("aria-valuenow", String(Math.round(job.progress * 100)));
  } else {
    ui.bar.removeAttribute("aria-valuenow");
  }
  if (job.stage === "downloading") {
    setButton("downloading", known ? ` ${Math.round(job.progress * 100)}%` : "");
    const got = formatBytes(job.downloaded_bytes);
    ui.text.textContent = job.expected_bytes
      ? `${got} of about ${formatBytes(job.expected_bytes)}`
      : got ? `${got} downloaded` : "Downloading";
  } else if (job.stage === "processing") {
    setButton("processing");
    ui.text.textContent = "Merging streams and converting. This can take a while on free hosting.";
  } else {
    setButton("preparing");
    ui.text.textContent = job.state === "queued" ? "Waiting for a free slot." : "Contacting the source.";
  }
}

async function startDownload() {
  if (state.job) return;
  const ctl = new AbortController();
  const job = (state.job = { id: null, ctl });
  const request = { url: state.url, type: state.type, quality: state.quality };
  const label = qualityLabel();
  ui.error.hidden = ui.done.hidden = true;
  setButton("preparing");
  ui.box.hidden = false;
  ui.bar.classList.add("indet");
  ui.text.textContent = state.server === "online" ? "Starting." : "Waking the server. This can take up to a minute.";
  try {
    if (state.server !== "online" && !(await connectServer())) {
      throw new ApiError("network", "Could not reach the FluxVid server. Check your connection and try again.");
    }
    let current = await createJob(request, ctl.signal);
    job.id = current.id;
    for (let failures = 0; ; ) {
      showProgress(current);
      if (current.state === "ready" || current.state === "failed") break;
      await sleep(1000, ctl.signal);
      try {
        current = await getJob(job.id, ctl.signal);
        failures = 0;
      } catch (err) {
        if (err.name === "AbortError" || err.code === "job_not_found" || ++failures >= 5) throw err;
        await sleep(2000, ctl.signal);
      }
    }
    if (current.state === "failed") throw new ApiError(current.error.code, current.error.message);
    handOff(current, request, label);
  } catch (err) {
    ui.box.hidden = true;
    setButton("idle");
    if (err.name === "AbortError") {
      if (job.id) cancelJob(job.id).catch(() => {});
    } else {
      ui.errorText.textContent = err.message;
      ui.error.hidden = false;
      renderHistory(addHistory({ filename: state.info.title, type: state.type, quality: label, status: "Failed", url: state.url }));
    }
  } finally {
    state.job = null;
  }
}

function handOff(job, request, label) {
  const href = fileUrl(job.file_url);
  const link = Object.assign(document.createElement("a"), { href });
  document.body.append(link);
  link.click();
  link.remove();
  ui.box.hidden = true;
  setButton("done");
  ui.btn.disabled = false;
  ui.doneName.textContent = job.filename;
  ui.saveAgain.href = href;
  ui.done.hidden = false;
  hydrateIcons(ui.done);
  renderHistory(addHistory({ filename: job.filename, type: request.type, quality: label, status: "Sent to browser", url: request.url }));
}

function cancelActiveJob() {
  state.job?.ctl.abort();
}

function reset() {
  cancelActiveJob();
  els.stage.replaceChildren();
  ui = null;
  els.input.value = "";
  syncClear();
  els.input.focus();
}

// ---------- recent links ----------
function renderRecent(list = loadRecent()) {
  els.recent.hidden = list.length === 0;
  els.recentList.replaceChildren(...list.map((item) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip-btn";
    b.title = item.url;
    b.textContent = item.title || item.url;
    b.addEventListener("click", () => analyze(item.url));
    return b;
  }));
}

// ---------- history ----------
function renderHistory(list = loadHistory()) {
  els.historyEmpty.hidden = list.length > 0;
  els.historyList.replaceChildren(...list.map((item) => {
    const li = document.createElement("li");
    li.className = "history-item";
    li.innerHTML = `<span class="ico">${icon(item.type === "audio" ? "audio" : "video")}</span>
      <div class="h-text"><p class="h-name"></p><p class="h-sub"></p></div>
      <button class="icon-btn small" type="button" data-act="again" aria-label="Open this link again">${icon("search")}</button>
      <button class="icon-btn small" type="button" data-act="copy" aria-label="Copy file name">${icon("copy")}</button>`;
    $(".h-name", li).textContent = item.filename;
    const sub = $(".h-sub", li);
    sub.textContent = `${item.quality} - ${item.status}`;
    sub.dataset.status = item.status;
    const again = $('[data-act="again"]', li);
    if (item.url) again.addEventListener("click", () => { toggleHistory(false); analyze(item.url); });
    else again.hidden = true;
    const copyBtn = $('[data-act="copy"]', li);
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(item.filename);
        copyBtn.innerHTML = icon("check");
        setTimeout(() => { copyBtn.innerHTML = icon("copy"); }, 1400);
      } catch { /* clipboard unavailable */ }
    });
    return li;
  }));
}

function toggleHistory(open) {
  els.history.hidden = !open;
  els.historyBtn.setAttribute("aria-expanded", String(open));
  (open ? $("#closeHistory") : els.historyBtn).focus();
}

// ---------- wiring ----------
els.form.addEventListener("submit", (e) => { e.preventDefault(); analyze(); });
els.paste.addEventListener("click", pasteFromClipboard);
els.input.addEventListener("input", () => { els.hint.textContent = ""; syncClear(); });
els.clearInput.addEventListener("click", () => { els.input.value = ""; syncClear(); els.input.focus(); });
els.historyBtn.addEventListener("click", () => toggleHistory(els.history.hidden));
$("#closeHistory").addEventListener("click", () => toggleHistory(false));
$("#clearHistory").addEventListener("click", () => renderHistory(clearHistory()));
$("#clearRecent").addEventListener("click", () => renderRecent(clearRecent()));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.history.hidden) toggleHistory(false); });

startIntro();
hydrateIcons();
renderHistory();
renderRecent();
if (API_BASE) connectServer(); else setServer("offline");
handleSharedLink();
if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
