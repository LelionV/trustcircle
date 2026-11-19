// Protected documents (KYC, loan files) are fetched with the access token and
// shown from a temporary blob URL. They never have a public address.

import { fetchFile } from "../api.js";
import { $$, html, toast } from "../ui.js";

const LABELS = { id_front: "Front", id_back: "Back", selfie: "Selfie", proof_of_income: "Proof of income" };

/** Buttons that open documents. files: { key: url } or [{ description, url }] */
export function documentLinks(files) {
  const items = Array.isArray(files)
    ? files.map((f) => [f.description, f.url])
    : Object.entries(files || {}).map(([k, url]) => [LABELS[k] || k, url]);
  if (!items.length) return html`<span class="muted">None</span>`;
  return html`<span class="doc-links">${items.map(([label, url]) =>
    html`<button class="btn btn--quiet btn--small" type="button" data-doc="${url}">${label}</button>`)}</span>`;
}

/** Image previews for review screens. */
export function documentPreviews(files) {
  return html`<div class="doc-grid">${Object.entries(files || {}).map(([k, url]) => html`
    <figure class="doc">
      <div class="doc__frame" data-preview="${url}"><span class="muted small">Loading…</span></div>
      <figcaption>${LABELS[k] || k} <button class="btn btn--quiet btn--small" type="button" data-doc="${url}">Open</button></figcaption>
    </figure>`)}</div>`;
}

export function wireDocuments(root) {
  $$("[data-doc]", root).forEach((btn) => btn.addEventListener("click", async () => {
    const win = window.open("", "_blank");
    try {
      const blob = await fetchFile(btn.dataset.doc);
      const url = URL.createObjectURL(blob);
      if (win) win.location.href = url;
      else window.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      if (win) win.close();
      toast(err.message, "error");
    }
  }));
  $$("[data-preview]", root).forEach(async (frame) => {
    try {
      const blob = await fetchFile(frame.dataset.preview);
      frame.textContent = "";
      if (blob.type.startsWith("image/")) {
        const img = document.createElement("img");
        img.alt = "";
        img.src = URL.createObjectURL(blob);
        frame.appendChild(img);
      } else {
        frame.textContent = "PDF document";
        frame.classList.add("doc__frame--pdf");
      }
    } catch {
      frame.textContent = "Couldn't load";
    }
  });
}
