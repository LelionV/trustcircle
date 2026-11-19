import { api } from "../api.js";
import { $, $$, formatDateTime, html, icon, mount } from "../ui.js";
import { actionName, emptyState, errorBlock, loadingBlock, pageHead } from "./common.js";
import { openDrawer } from "./drawer.js";
import { pager } from "./pager.js";

const pretty = (v) => (v == null ? "None" : JSON.stringify(v, null, 2));

export async function auditView(el, ctx) {
  const q = {
    search: ctx.query.get("search") || "",
    entity_id: ctx.query.get("entity_id") || "",
    page: ctx.query.get("page") || "1",
  };
  mount(el, html`
    ${pageHead("Audit trail", "Every administrator action and configuration change. Entries can't be edited or deleted.")}
    <form class="filters" id="audit-filters" role="search">
      <label class="field field--search"><span class="sr-only">Search</span>
        ${icon("search", "icon icon--sm")}
        <input type="search" name="search" placeholder="Action, reason, admin email or record id" value="${q.search}"></label>
      <button class="btn btn--quiet" type="submit">Search</button>
      ${q.entity_id ? html`<a class="btn btn--quiet" href="#/admin/audit">Show all records</a>` : ""}
    </form>
    ${q.entity_id ? html`<p class="muted small">Showing entries for record ${q.entity_id}</p>` : ""}
    <div id="audit-results">${loadingBlock()}</div>`);

  const form = $("#audit-filters", el);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    ctx.navigate("/admin/audit", { search: form.search.value.trim(), entity_id: q.entity_id });
  });

  const host = $("#audit-results", el);
  let data;
  try {
    data = await api.get("admin/audit-logs/", q);
  } catch (err) {
    mount(host, errorBlock(err));
    return;
  }
  if (!data.results.length) {
    mount(host, emptyState("No entries", q.search || q.entity_id ? "Nothing matches that search." : "Administrator actions will appear here as they happen."));
    return;
  }
  mount(host, html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th scope="col">When</th><th scope="col">What happened</th><th scope="col">Record</th><th scope="col">By</th><th scope="col">Reason</th></tr></thead>
        <tbody>${data.results.map((a, i) => html`<tr>
          <td class="nowrap">${formatDateTime(a.created_at)}</td>
          <td><button class="linkish" type="button" data-entry="${i}">${actionName(a.action)}</button></td>
          <td>${a.entity_type}<span class="sub">${a.entity_id}</span></td>
          <td>${a.actor_email || "System"}</td>
          <td class="clip">${a.reason || html`<span class="muted">None given</span>`}</td>
        </tr>`)}</tbody>
      </table>
    </div>
    ${pager(data, Number(q.page))}`);

  $$("[data-entry]", host).forEach((b) => b.addEventListener("click", () => {
    const a = data.results[Number(b.dataset.entry)];
    openDrawer(html`
      <h2 id="drawer-title">${actionName(a.action)}</h2>
      <p class="muted">${formatDateTime(a.created_at)}</p>
      <table class="kv">
        <tr><th scope="row">By</th><td>${a.actor_email || "System"}</td></tr>
        <tr><th scope="row">Record</th><td>${a.entity_type} ${a.entity_id}</td></tr>
        <tr><th scope="row">Reason</th><td>${a.reason || "None given"}</td></tr>
        <tr><th scope="row">IP address</th><td>${a.ip_address || "Unknown"}</td></tr>
        <tr><th scope="row">Request reference</th><td>${a.request_id || "None"}</td></tr>
      </table>
      <h3>Before</h3><pre class="code">${pretty(a.before)}</pre>
      <h3>After</h3><pre class="code">${pretty(a.after)}</pre>`);
  }));
  $$("[data-page]", host).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/audit", { ...q, page: b.dataset.page })));
}
