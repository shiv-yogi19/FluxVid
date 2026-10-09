// Individual SVG files are fetched once and inlined so they inherit currentColor.
const cache = new Map();

function load(name) {
  if (!cache.has(name)) {
    cache.set(name, fetch(`assets/icons/${name}.svg`).then((r) => (r.ok ? r.text() : "")).catch(() => ""));
  }
  return cache.get(name);
}

export async function setIcon(el, name) {
  el.dataset.icon = name;
  el.innerHTML = await load(name);
  el.setAttribute("aria-hidden", "true");
}

export function hydrateIcons(root = document) {
  return Promise.all([...root.querySelectorAll("[data-icon]")].map((el) => setIcon(el, el.dataset.icon)));
}
