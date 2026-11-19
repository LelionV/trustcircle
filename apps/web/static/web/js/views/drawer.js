import { icon, mount, html } from "../ui.js";

let lastFocus = null;

function onKey(ev) {
  if (ev.key === "Escape") closeDrawer();
}

/** Side panel for record details. Returns the panel element. */
export function openDrawer(content) {
  closeDrawer();
  lastFocus = document.activeElement;
  const root = document.createElement("div");
  root.className = "drawer";
  root.id = "drawer";
  mount(root, html`<div class="drawer__scrim" data-close></div>
    <aside class="drawer__panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title" tabindex="-1">
      <button class="icon-btn drawer__close" type="button" data-close aria-label="Close">${icon("close")}</button>
      <div class="drawer__body">${content}</div>
    </aside>`);
  document.body.appendChild(root);
  root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", onKey);
  const panel = root.querySelector(".drawer__panel");
  requestAnimationFrame(() => {
    root.classList.add("is-open");
    panel.focus();
  });
  return panel;
}

export function closeDrawer() {
  const root = document.getElementById("drawer");
  if (!root) return;
  document.removeEventListener("keydown", onKey);
  root.remove();
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  lastFocus = null;
}
