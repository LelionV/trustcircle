// Helpers shared by the wallet, investing, guarantee, chat and admin pages (phases 5–10).
import { fetchFile } from "../api.js";
import { formatMoney, html, toast } from "../ui.js";

export const BASIS_SHORT = { MONTHLY: "a month", ANNUAL: "a year", PER_LOAN: "for the loan" };

/** "2.50% a month" — the rate type comes from the server (admins choose it). */
export const rateText = (rate, basis) => (rate == null || rate === "" ? "Not set" : `${rate}% ${BASIS_SHORT[basis] || ""}`.trim());

export const money = (v) => (v == null || v === "" ? "–" : formatMoney(v));

const TONES = {
  ok: ["SUCCEEDED", "ACCEPTED", "ACTIVE", "COMPLETED", "APPROVED", "RECOVERED", "RESOLVED", "PAID_EARLY", "PAID_ON_TIME", "READY_FOR_DISBURSEMENT", "DISBURSED", "FULLY_FUNDED"],
  info: ["PENDING", "PROCESSING", "REQUESTED", "OPEN", "AWAITING_CONSENT", "IN_PROGRESS", "COMMITTED", "UPCOMING", "DUE", "PARTIALLY_PAID", "GUARANTOR_PENDING", "PUBLISHED", "PARTIALLY_FUNDED", "NOMINATED"],
  warn: ["AWAITING_APPROVAL", "OVERDUE", "PAID_LATE", "PARTLY_RECOVERED", "WARNED"],
  bad: ["FAILED", "REJECTED", "DEFAULTED", "DECLINED", "CLAIMED", "WRITTEN_OFF", "ACTIONED"],
};
export function statusTag(status, label) {
  const tone = Object.entries(TONES).find(([, list]) => list.includes(status))?.[0];
  return html`<span class="tag ${tone ? `tag--${tone}` : ""}">${label || status}</span>`;
}

/** Download a protected CSV/file with the access token. */
export async function download(url, filename) {
  try {
    const blob = await fetchFile(url);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (err) { toast(err.message, "error"); }
}

/** A row of headline numbers. items: [[label, value, note?]] */
export const stats = (items) => html`<div class="stats">${items.map(([label, value, note]) => html`
  <div class="stat"><p class="stat__label">${label}</p><p class="stat__value">${value}</p>${note ? html`<p class="stat__note">${note}</p>` : ""}</div>`)}</div>`;

/** Fresh idempotency key per form submission so a double click never pays twice. */
export const idemKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** Prompt-free confirmation with the exact figures, using the browser dialog. */
export const confirmAction = (text) => window.confirm(text);
