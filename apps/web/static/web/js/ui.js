// Rendering helpers. Every interpolated value is HTML-escaped unless it is
// wrapped in raw(); never pass user data to raw().

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}

export const raw = (s) => new Raw(String(s));

function renderValue(v) {
  if (v === null || v === undefined || v === false) return "";
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(renderValue).join("");
  return esc(v);
}

/** Tagged template: html`<p>${userText}</p>` escapes userText. */
export function html(strings, ...values) {
  let out = "";
  strings.forEach((str, i) => {
    out += str;
    if (i < values.length) out += renderValue(values[i]);
  });
  return new Raw(out);
}

export function mount(el, content) {
  el.innerHTML = String(content);
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// --- Formatting ----------------------------------------------------------

const TZ = "Africa/Nairobi";
const dateFmt = new Intl.DateTimeFormat("en-KE", { dateStyle: "medium", timeZone: TZ });
const dateTimeFmt = new Intl.DateTimeFormat("en-KE", { dateStyle: "medium", timeStyle: "short", timeZone: TZ });

export const formatDate = (iso) => (iso ? dateFmt.format(new Date(iso)) : "Never");
export const formatDateTime = (iso) => (iso ? dateTimeFmt.format(new Date(iso)) : "Never");

/** Amounts arrive as decimal strings; format without converting to floats. */
export function formatMoney(amount, currency = "KES") {
  const s = String(amount).trim();
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new Error(`Not a decimal amount: ${amount}`);
  const negative = s.startsWith("-");
  const [wholeRaw, frac = ""] = (negative ? s.slice(1) : s).split(".");
  const whole = wholeRaw.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const cents = (frac + "00").slice(0, 2);
  return `${negative ? "-" : ""}${currency} ${whole}.${cents}`;
}

export function initials(name) {
  return name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
}

export function greeting(now = new Date()) {
  const hour = Number(new Intl.DateTimeFormat("en-KE", { hour: "numeric", hourCycle: "h23", timeZone: TZ }).format(now));
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

// --- Toasts ----------------------------------------------------------------

export function toast(message, kind = "info") {
  const host = document.getElementById("toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast toast--${kind}`;
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// --- Icons (24px, stroke = currentColor) -----------------------------------

const PATHS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  loan: "M4 6h16v12H4zM4 10h16M8 15h3",
  apply: "M12 5v14M5 12h14",
  repay: "M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4",
  trust: "M4 18h3v-4H4zm6.5 0h3V10h-3zM17 18h3V6h-3z",
  market: "M4 7h16l-1.5 11h-13zM8 7a4 4 0 0 1 8 0",
  portfolio: "M3 8h18v12H3zM8 8V5h8v3M3 13h18",
  statement: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6",
  shield: "M12 3 5 6v6c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6z",
  commission: "M12 3v18M16.5 7.5c0-1.7-2-3-4.5-3s-4.5 1.3-4.5 3S9.5 10.5 12 11s4.5 1.3 4.5 3.2S14.5 17.5 12 17.5 7.5 16.2 7.5 14.5",
  wallet: "M3 7h15a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7l12-3v3M16 13h1",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  id: "M3 5h18v14H3zM8.5 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM5.5 16a3 3 0 0 1 6 0M14 9h4M14 13h4",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  users: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.3a3.5 3.5 0 0 1 0 6.4M18 14a6.5 6.5 0 0 1 3.5 6",
  check: "M4 12.5 9 17.5 20 6.5",
  review: "M9 11l2 2 4-4M5 3h14v18H5z",
  ledger: "M5 3h14v18H5zM9 3v18M12 8h4M12 12h4M12 16h4",
  withdraw: "M12 4v12M7 11l5 5 5-5M5 20h14",
  report: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  audit: "M12 8v4l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6 6 18",
  lock: "M6 11h12v10H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  snow: "M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9",
  cloud: "M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 10a4 4 0 0 1 0 8zM4 4l16 16",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  chat: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  flag: "M5 21V4M5 4h11l-2 4 2 4H5",
  alert: "M12 3 2 20h20zM12 10v4M12 17v.5",
};

export function icon(name, cls = "icon") {
  const d = PATHS[name] || PATHS.grid;
  return raw(
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ` +
      `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="${d}"/></svg>`
  );
}
