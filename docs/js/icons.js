// Icons come from one SVG sprite (assets/icons.svg), so they inherit currentColor.
export const icon = (name) =>
  `<svg class="i" aria-hidden="true" focusable="false"><use href="assets/icons.svg#${name}"></use></svg>`;

export function setIcon(el, name) {
  el.dataset.icon = name;
  el.innerHTML = icon(name);
}

export function hydrateIcons(root = document) {
  for (const el of root.querySelectorAll("[data-icon]")) el.innerHTML = icon(el.dataset.icon);
}
