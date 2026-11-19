// The interest bracket ruler: trust score 0–100 left to right, with the
// annual rate for each bracket. Data comes from GET /pricing/brackets/.

import { html, $$ } from "../ui.js";

const span = (b) => b.max_score - b.min_score + 1;
const rate = (b) => (b.manual_review ? "Review" : `${Number.parseFloat(b.annual_rate)}%`);

export function ruler(set, { marker } = {}) {
  const brackets = [...set.brackets].sort((a, b) => a.min_score - b.min_score);
  let tier = 0;
  return html`<figure class="ruler">
    <div class="ruler__cols">
      ${brackets.map((b) => {
        const cls = b.manual_review ? "seg-review" : `seg-${++tier}`;
        return html`<div class="ruler__col" data-span="${span(b)}" data-min="${b.min_score}" data-max="${b.max_score}">
          <p class="ruler__rate">${rate(b)}</p>
          <div class="ruler__bar ${cls}"></div>
          <p class="ruler__label">${b.label}</p>
          <p class="ruler__range">${b.min_score}–${b.max_score}</p>
        </div>`;
      })}
      ${marker ? html`<div class="ruler__marker" data-pos="${marker.score}">
        <span class="ruler__pin" aria-hidden="true"></span>
        <span class="ruler__note">${marker.label}</span>
      </div>` : ""}
    </div>
    <figcaption class="sr-only">
      Annual interest by trust score: ${brackets.map((b) => `${b.min_score} to ${b.max_score}, ${rate(b)}`).join("; ")}.
    </figcaption>
  </figure>`;
}

/** Widths and the marker position are set through the CSSOM (CSP forbids inline styles). */
export function layoutRuler(root) {
  const total = $$(".ruler__col", root).reduce((n, c) => n + Number(c.dataset.span), 0) || 101;
  $$(".ruler__col", root).forEach((c) => { c.style.flexGrow = c.dataset.span; });
  $$(".ruler__marker", root).forEach((m) => {
    // Narrow screens stack the brackets; there the bracket row carries the note instead.
    const score = Number(m.dataset.pos);
    const col = $$(".ruler__col", root).find((c) => score >= Number(c.dataset.min) && score <= Number(c.dataset.max));
    if (col) {
      col.classList.add("has-marker");
      col.dataset.note = m.querySelector(".ruler__note").textContent;
    }
    const pos = ((Number(m.dataset.pos) + 0.5) / total) * 100;
    m.style.setProperty("--pos", `${pos}%`);
    requestAnimationFrame(() => m.classList.add("is-placed"));
  });
}
