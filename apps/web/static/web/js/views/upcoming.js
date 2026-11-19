import { html, icon, mount } from "../ui.js";

/** A page the user is allowed to see, whose backend arrives in a later phase. */
export function upcomingView(phase, purpose, contents) {
  return (el, { route }) => mount(el, html`
    <header class="page-head">
      <h1>${route.title}</h1>
      <p class="lead">${purpose}</p>
    </header>
    <section class="panel upcoming">
      <div class="upcoming__badge">${icon(route.icon)}<span>Opens in phase ${phase}</span></div>
      <h2>What you'll find here</h2>
      <ul class="ticks">${contents.map((c) => html`<li>${c}</li>`)}</ul>
      <p class="muted small">You can see this page because your role includes it. Nothing here moves money yet.</p>
      <a class="btn btn--quiet" href="#/">Back to dashboard</a>
    </section>`);
}

export function forbiddenView(el, { route }) {
  mount(el, html`<header class="page-head"><h1>You don't have access to ${route.title.toLowerCase()}</h1>
    <p class="lead">Your role doesn't include this page. If you need it for your work, ask a super administrator.</p></header>
    <a class="btn btn--quiet" href="#/">Back to dashboard</a>`);
}

export function notFoundView(el) {
  mount(el, html`<header class="page-head"><h1>Page not found</h1>
    <p class="lead">The link may be out of date. Use the menu to find what you need.</p></header>
    <a class="btn btn--quiet" href="#/">Back to dashboard</a>`);
}
