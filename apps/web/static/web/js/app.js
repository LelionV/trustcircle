// Web app entry point: health check → session → shell + router.

import * as API from "./api.js";
import { findRoute, ROUTES, SECTIONS } from "./routes.js";
import { can, setUser, user } from "./session.js";
import { $, $$, html, icon, initials, mount } from "./ui.js";
import { errorBlock } from "./views/common.js";
import { closeDrawer } from "./views/drawer.js";
import { loginView } from "./views/login.js";
import { registerView } from "./views/register.js";
import { termsView } from "./views/terms.js";
import { forbiddenView, notFoundView } from "./views/upcoming.js";

const app = document.getElementById("app");
let shellReady = false;

// --- Routing -----------------------------------------------------------------

function parseHash() {
  const h = location.hash.replace(/^#/, "") || "/";
  const [path, qs = ""] = h.split("?");
  return { path: path || "/", query: new URLSearchParams(qs) };
}

export function navigate(path, query = {}) {
  const qs = new URLSearchParams(
    Object.entries(query).filter(([k, v]) => v !== "" && v != null && !(k === "page" && String(v) === "1"))
  );
  const target = `#${path}${[...qs].length ? `?${qs}` : ""}`;
  if (location.hash === target) renderRoute();
  else location.hash = target;
}

async function renderRoute({ focus = true } = {}) {
  if (!shellReady) return;
  closeDrawer();
  document.body.classList.remove("nav-open");
  const { path, query } = parseHash();
  const match = findRoute(path);
  const route = match ? match.route : null;
  const view = $("#view");
  const navPath = route ? route.parent || route.path : path;

  $$(".nav__link").forEach((a) => {
    if (a.dataset.path === navPath) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = `${route ? route.title : "Not found"} | P2P Lend`;

  const ctx = {
    route, query, params: match ? match.params : {}, navigate,
    rerender: () => renderRoute({ focus: false }),
    refreshShell: () => { renderShell(); },
    refreshUser: async () => { setUser(await API.request("accounts/me/")); },
  };
  try {
    if (!route) notFoundView(view, ctx);
    else if (!can(route.perm)) forbiddenView(view, ctx);
    else await route.render(view, ctx);
  } catch (err) {
    mount(view, errorBlock(err));
  }
  if (focus) view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// --- Shell ---------------------------------------------------------------------

function navMarkup() {
  return SECTIONS.map((section) => {
    const items = ROUTES.filter((r) => !r.hidden && r.section === section && can(r.perm));
    if (!items.length) return "";
    return html`<div class="nav__group">
      ${section ? html`<p class="nav__heading">${section}</p>` : ""}
      ${items.map((r) => html`<a class="nav__link" href="#${r.path}" data-path="${r.path}">
        ${icon(r.icon)}<span>${r.title}</span>${r.badge ? html`<span class="nav__badge" data-badge="${r.badge}" hidden></span>` : ""}
      </a>`)}
    </div>`;
  });
}

function renderShell() {
  const u = user();
  const ADMIN_TITLES = { SUPPORT: "Support admin", OPERATIONS: "Operations admin", FINANCE: "Finance admin", SUPER: "Super admin", NONE: "Administrator" };
  const roleLine = u.role === "ADMIN" ? ADMIN_TITLES[u.admin_level] : u.role_label;
  mount(app, html`
    <div class="shell">
      <aside class="sidebar" id="sidebar" aria-label="Main menu">
        <div class="brand"><span class="brand__mark"></span><span>P2P Lend</span></div>
        <nav class="nav">${navMarkup()}</nav>
        <div class="me">
          <span class="me__avatar" aria-hidden="true">${initials(u.full_name)}</span>
          <div class="me__text"><p class="me__name">${u.full_name}</p><p class="me__role">${roleLine}</p></div>
          <button class="icon-btn" type="button" id="sign-out" aria-label="Sign out" title="Sign out">${icon("logout")}</button>
        </div>
      </aside>
      <div class="scrim" data-close-nav></div>
      <div class="main">
        <header class="topbar">
          <button class="icon-btn" type="button" id="open-nav" aria-label="Open menu" aria-controls="sidebar">${icon("menu")}</button>
          <div class="brand"><span class="brand__mark"></span><span>P2P Lend</span></div>
        </header>
        ${u.is_frozen ? html`<div class="banner banner--frozen" role="status">${icon("snow", "icon icon--sm")}
          <p>Your account is frozen. You can still sign in, view everything and make repayments, but withdrawals, transfers and new applications or investments are paused. Contact support to resolve it.</p></div>` : ""}
        <main id="view" class="view" tabindex="-1"></main>
      </div>
    </div>`);

  $("#sign-out").addEventListener("click", async () => {
    await API.logout();
    signedOut("You've signed out.");
  });
  $("#open-nav").addEventListener("click", () => document.body.classList.add("nav-open"));
  $$("[data-close-nav]").forEach((el) => el.addEventListener("click", () => document.body.classList.remove("nav-open")));
  shellReady = true;
  renderRoute({ focus: false });
  refreshBadges();
}

// Unread counts for the sidebar (notifications and chat), refreshed every 30 seconds.
let badgeTimer = null;
async function refreshBadges() {
  clearTimeout(badgeTimer);
  if (!shellReady) return;
  try {
    const counts = await API.request("notifications/unread/");
    $$("[data-badge]").forEach((b) => {
      const n = counts[b.dataset.badge] || 0;
      b.hidden = n === 0;
      b.textContent = n > 99 ? "99+" : String(n);
    });
  } catch { /* offline or signed out; try again later */ }
  badgeTimer = setTimeout(refreshBadges, 30000);
}
window.addEventListener("p2p:badges", refreshBadges);

async function startSession(u) {
  setUser(u);
  try {
    const legal = await API.request("legal/current/");
    if (legal.terms && !legal.accepted) {
      showTerms();
      return;
    }
  } catch (err) {
    if (err.code === "network_error") { connectionError(err); return; }
  }
  renderShell();
}

// Full-page terms screen: shown until the current version is accepted.
function showTerms() {
  shellReady = false;
  termsView(app, {
    onAccepted: async () => startSession(await API.request("accounts/me/")),
    onSignOut: async () => {
      await API.logout();
      signedOut("You've signed out.");
    },
  });
}

// A new version published while someone is signed in asks them to accept it.
window.addEventListener("p2p:terms-required", () => {
  if (user()) showTerms();
});

function signedOut(message) {
  shellReady = false;
  setUser(null);
  closeDrawer();
  if (parseHash().path === "/register") {
    document.title = "Create an account | P2P Lend";
    registerView(app, { onSignedIn: (u) => { location.hash = "#/"; startSession(u); } });
    return;
  }
  document.title = "Sign in | P2P Lend";
  loginView(app, { message, onSignedIn: startSession });
}

// --- Start-up ------------------------------------------------------------------

function splash() {
  mount(app, html`<div class="splash"><div class="brand"><span class="brand__mark"></span><span>P2P Lend</span></div>
    <p class="loading" role="status">Connecting…</p></div>`);
}

function connectionError(err) {
  const message = err.status === 503
    ? "The server is running but can't reach its database. Try again in a moment."
    : err.message;
  mount(app, html`<div class="splash">
    ${icon("cloud", "icon icon--lg")}
    <h1>Can't reach P2P Lend</h1>
    <p>${message}</p>
    <button class="btn" type="button" id="retry">Try again</button>
  </div>`);
  $("#retry").addEventListener("click", boot);
}

async function boot() {
  splash();
  try {
    await API.health();
  } catch (err) {
    connectionError(err);
    return;
  }
  let u = null;
  try {
    u = await API.restoreSession();
  } catch (err) {
    if (err.code === "network_error") { connectionError(err); return; }
    API.clearSession();
  }
  if (u) startSession(u);
  else signedOut();
}

window.addEventListener("hashchange", () => {
  if (shellReady) renderRoute();
  else if (user() === null && ["/register", "/login", "/"].includes(parseHash().path)) signedOut();
});
window.addEventListener("p2p:session-expired", () => {
  API.clearSession();
  signedOut("Your session has ended. Sign in again to continue.");
});

boot();
