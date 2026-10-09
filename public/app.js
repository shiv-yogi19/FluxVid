import { hydrateIcons, setIcon } from "./js/icons.js";
import { getInfo, downloadMedia } from "./js/api.js";
import { loadHistory, addHistory, clearHistory } from "./js/history.js";

const $ = (sel, root = document) => root.querySelector(sel);
const slot = (root, name) => root.querySelector(`[data-slot="${name}"]`);

const els = {
  form: $("#urlForm"), field: $("#field"), input: $("#urlInput"), hint: $("#urlHint"),
  paste: $("#pasteBtn"), analyze: $("#analyzeBtn"), stage: $("#stage"),
  historyBtn: $("#historyBtn"), history: $("#history"), historyList: $("#historyList"), historyEmpty: $("#historyEmpty"),
};
const state = { info: null, url: "", type: "video", quality: null, analyzeCtl: null, downloadCtl: null };
let media = null; // refs into the rendered media card

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

// ---------- helpers ----------
function formatDuration(total) {
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function parseUrl(raw) {
  try {
    const u = new URL(raw.trim());
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch { return null; }
}

function showStage(node) {
  els.stage.replaceChildren(node);
  hydrateIcons(node);
}

function flashIcon(el, name, original, label, text, ms = 1600) {
  setIcon(el, name);
  const prev = label.textContent;
  if (text) label.textContent = text;
  setTimeout(() => { setIcon(el, original); label.textContent = prev; }, ms);
}

// ---------- paste ----------
async function pasteFromClipboard() {
  const icon = $(".ico", els.paste), label = $(".lbl", els.paste);
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) throw new Error("empty");
    els.input.value = text;
    els.hint.textContent = "";
    flashIcon(icon, "check", "paste", label, "Pasted");
  } catch {
    els.input.focus();
    els.hint.textContent = "Clipboard access is blocked. Press and hold the field to paste.";
  }
}

// ---------- analyze ----------
async function analyze() {
  const url = parseUrl(els.input.value);
  if (!url) {
    els.hint.textContent = "Enter a valid link that starts with http or https.";
    els.input.focus();
    return;
  }
  els.hint.textContent = "";
  state.analyzeCtl?.abort();
  const ctl = (state.analyzeCtl = new AbortController());
  showStage($("#tpl-loading").content.cloneNode(true));
  els.analyze.disabled = true;
  try {
    const info = await getInfo(url, ctl.signal);
    Object.assign(state, { info, url, type: info.types[0], quality: null });
    renderMedia();
  } catch (err) {
    if (err.name !== "AbortError") renderError(err.message);
  } finally {
    if (state.analyzeCtl === ctl) els.analyze.disabled = false;
  }
}

function renderError(message) {
  const node = $("#tpl-error").content.cloneNode(true);
  slot(node, "text").textContent =
    message || "The source may be unsupported, private, DRM-protected, restricted, or temporarily unavailable.";
  slot(node, "retry").addEventListener("click", analyze);
  showStage(node);
}

// ---------- media card ----------
function renderMedia() {
  const { info } = state;
  const node = $("#tpl-media").content.cloneNode(true);
  const root = $(".media", node);

  slot(root, "title").textContent = info.title;
  const kinds = info.types.length === 2 ? "Video and audio found" : info.types[0] === "video" ? "Video found" : "Audio found";
  slot(root, "found").textContent = kinds;
  if (info.duration) slot(root, "duration").textContent = formatDuration(info.duration);
  else slot(root, "durationChip").hidden = true;
  if (info.platform) slot(root, "platform").textContent = info.platform;
  else slot(root, "platformChip").hidden = true;
  slot(root, "best").textContent = info.video.length ? `Up to ${info.video[0].label}` : "Audio only";

  const thumb = slot(root, "thumb");
  if (info.thumbnail) {
    const img = new Image();
    img.src = info.thumbnail;
    img.alt = "";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    thumb.prepend(img);
  }
  if (info.source_url) thumb.href = info.source_url;
  else thumb.removeAttribute("href");

  media = {
    root, seg: $("#seg", root), qualities: $("#qualities", root), output: slot(root, "output"),
    btn: $("#downloadBtn", root), icon: slot(root, "dlIcon"), label: slot(root, "dlLabel"),
    progress: $("#progress", root), cancel: $("#cancelBtn", root), error: $("#dlError", root), done: $("#done", root),
  };
  for (const b of media.seg.querySelectorAll("button")) {
    b.disabled = !info.types.includes(b.dataset.type);
    b.addEventListener("click", () => selectType(b.dataset.type));
  }
  media.btn.addEventListener("click", startDownload);
  media.cancel.addEventListener("click", () => state.downloadCtl?.abort());
  $("#backBtn", root).addEventListener("click", reset);

  showStage(node);
  selectType(state.type);
}

function selectType(type) {
  state.type = type;
  media.seg.dataset.value = type;
  for (const b of media.seg.querySelectorAll("button")) b.setAttribute("aria-checked", String(b.dataset.type === type));
  const options = state.info[type];
  state.quality = options[0].id;
  media.qualities.replaceChildren(
    ...options.map((opt) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "q";
      b.setAttribute("role", "radio");
      b.dataset.id = opt.id;
      b.textContent = opt.label;
      b.addEventListener("click", () => selectQuality(opt.id));
      return b;
    })
  );
  media.output.textContent = `Saved as ${state.info[type + "_format"]}`;
  syncQualities();
  resetDownloadUi();
}

function selectQuality(id) {
  state.quality = id;
  syncQualities();
  resetDownloadUi();
}

function syncQualities() {
  for (const b of media.qualities.children) b.setAttribute("aria-checked", String(b.dataset.id === state.quality));
}

function qualityLabel() {
  return state.info[state.type].find((o) => o.id === state.quality)?.label ?? state.quality;
}

// ---------- download ----------
const BUTTON = {
  idle: ["download", "Download"],
  preparing: ["spinner", "Preparing..."],
  downloading: ["spinner", "Downloading"],
  done: ["check", "Downloaded"],
};

function setButton(name, extra = "") {
  const [icon, text] = BUTTON[name];
  media.btn.dataset.state = name;
  if (media.icon.dataset.icon !== icon) setIcon(media.icon, icon);
  media.icon.classList.toggle("spin", name === "preparing" || name === "downloading");
  media.icon.classList.toggle("draw", name === "done");
  media.label.textContent = text + extra;
  media.btn.setAttribute("aria-busy", String(name === "preparing" || name === "downloading"));
}

function setProgress(fraction) {
  const bar = media.progress;
  bar.hidden = false;
  bar.classList.toggle("indet", fraction === null);
  if (fraction !== null) {
    bar.style.setProperty("--p", fraction.toFixed(3));
    media.label.textContent = `Downloading ${Math.round(fraction * 100)}%`;
  }
}

function resetDownloadUi() {
  if (!media || state.downloadCtl) return;
  setButton("idle");
  media.progress.hidden = true;
  media.done.hidden = true;
  media.error.hidden = true;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function startDownload() {
  if (state.downloadCtl) return;
  const ctl = (state.downloadCtl = new AbortController());
  const { url, type, info } = state;
  const quality = qualityLabel();
  media.done.hidden = true;
  media.error.hidden = true;
  media.cancel.hidden = false;
  media.progress.hidden = true;
  setButton("preparing");
  try {
    const { blob, filename } = await downloadMedia(
      { url, type, quality: state.quality },
      { signal: ctl.signal, onReady: () => { setButton("downloading"); setProgress(null); }, onProgress: setProgress }
    );
    saveBlob(blob, filename);
    setButton("done");
    media.progress.hidden = true;
    slot(media.done, "doneName").textContent = filename;
    media.done.hidden = false;
    hydrateIcons(media.done);
    renderHistory(addHistory({ filename, type, quality, status: "Downloaded" }));
  } catch (err) {
    media.progress.hidden = true;
    setButton("idle");
    if (err.name !== "AbortError") {
      media.error.textContent = err.message;
      media.error.hidden = false;
      renderHistory(addHistory({ filename: info.title, type, quality, status: "Failed" }));
    }
  } finally {
    state.downloadCtl = null;
    media.cancel.hidden = true;
  }
}

function reset() {
  state.downloadCtl?.abort();
  els.stage.replaceChildren();
  media = null;
  els.input.value = "";
  els.input.focus();
}

// ---------- history ----------
function renderHistory(list = loadHistory()) {
  els.historyEmpty.hidden = list.length > 0;
  els.historyList.replaceChildren(
    ...list.map((item) => {
      const li = document.createElement("li");
      li.className = "history-item";
      li.innerHTML = `<span class="ico" data-icon="${item.type === "audio" ? "audio" : "video"}"></span>
        <div class="h-text"><p class="h-name"></p><p class="h-sub"></p></div>
        <button class="icon-btn" type="button" aria-label="Copy file name"><span class="ico" data-icon="copy"></span></button>`;
      $(".h-name", li).textContent = item.filename;
      const sub = $(".h-sub", li);
      sub.textContent = `${item.quality} - ${item.status}`;
      sub.dataset.status = item.status;
      const copyBtn = $("button", li);
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(item.filename);
          const icon = $(".ico", copyBtn);
          setIcon(icon, "check");
          setTimeout(() => setIcon(icon, "copy"), 1400);
        } catch { /* clipboard unavailable */ }
      });
      return li;
    })
  );
  hydrateIcons(els.historyList);
}

function toggleHistory(open) {
  els.history.hidden = !open;
  els.historyBtn.setAttribute("aria-expanded", String(open));
  if (open) $("#closeHistory").focus();
  else els.historyBtn.focus();
}

// ---------- wiring ----------
els.form.addEventListener("submit", (e) => { e.preventDefault(); analyze(); });
els.paste.addEventListener("click", pasteFromClipboard);
els.input.addEventListener("input", () => { els.hint.textContent = ""; });
els.historyBtn.addEventListener("click", () => toggleHistory(els.history.hidden));
$("#closeHistory").addEventListener("click", () => toggleHistory(false));
$("#clearHistory").addEventListener("click", () => renderHistory(clearHistory()));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.history.hidden) toggleHistory(false); });

startIntro();
hydrateIcons();
renderHistory();
