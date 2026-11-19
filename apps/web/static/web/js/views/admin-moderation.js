// Staff: disputes, user reports and support chats.
import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, emptyState, field, loadingBlock, pageHead } from "./common.js";
import { openDrawer } from "./drawer.js";
import { pager } from "./pager.js";
import { statusTag } from "./shared.js";

export async function adminDisputesView(el, ctx) {
  const status = ctx.query.has("status") ? ctx.query.get("status") : "OPEN";
  const page = ctx.query.get("page") || "1";
  mount(el, html`${pageHead("Disputes")}${loadingBlock()}`);
  const data = await api.get("admin/disputes/", { status, page });
  const tabs = [["OPEN", "Open"], ["IN_PROGRESS", "Being looked at"], ["RESOLVED", "Resolved"], ["REJECTED", "Closed"], ["", "All"]];
  mount(el, html`${pageHead("Disputes")}
    <nav class="tabs">${tabs.map(([k, l]) => html`<a class="tabs__tab" href="#/admin/disputes?status=${k}" ${k === status ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    ${data.results.length ? html`<section class="panel"><table class="table table--plain"><thead><tr><th scope="col">Reference</th><th scope="col">Customer</th><th scope="col">Subject</th><th scope="col">Status</th><th scope="col">Raised</th><th></th></tr></thead>
      <tbody>${data.results.map((d, i) => html`<tr><td>${d.reference}</td><td>${d.raised_by.name}<span class="sub">${d.raised_by.email}</span></td>
        <td>${d.subject}<span class="sub">${d.category_label}${d.loan ? ` · ${d.loan}` : ""}</span></td><td>${statusTag(d.status, d.status_label)}</td>
        <td class="nowrap">${formatDateTime(d.created_at)}</td><td><button class="btn btn--quiet btn--small" data-open="${i}">Open</button></td></tr>`)}</tbody></table>${pager(data, Number(page))}</section>`
      : html`<section class="panel">${emptyState("Nothing here", "Disputes raised by customers appear here.")}</section>`}`);
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/disputes", { status, page: b.dataset.page })));
  $$("[data-open]", el).forEach((b) => b.addEventListener("click", () => {
    const d = data.results[Number(b.dataset.open)];
    const panel = openDrawer(html`<h2 id="drawer-title">${d.reference}: ${d.subject}</h2>
      <p class="muted">${d.raised_by.name} · ${d.category_label} · ${formatDateTime(d.created_at)}</p>
      <blockquote class="quote-block">${d.description}</blockquote>
      <table class="kv"><tr><th scope="row">Loan</th><td>${d.loan || "–"}</td></tr><tr><th scope="row">Transaction</th><td>${d.transaction_reference || "–"}</td></tr>
        <tr><th scope="row">Handled by</th><td>${d.assigned_to || "Nobody yet"}</td></tr></table>
      ${can("admin.disputes.manage") ? html`<form class="form" id="dispute-form">
        ${field("status", "Status", html`<select name="status">${tabs.slice(0, 4).map(([k, l]) => html`<option value="${k}" ${k === d.status ? "selected" : ""}>${l}</option>`)}</select>`)}
        ${field("resolution", "Outcome / reply to the customer", html`<textarea name="resolution" rows="4">${d.resolution}</textarea>`, "Required to resolve or close. The customer is notified.")}
        <button class="btn" type="submit">Save</button></form>` : ""}`);
    $("#dispute-form", panel)?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.currentTarget;
      try { await busy(f.querySelector("button"), "Saving…", () => api.post(`admin/disputes/${d.id}/`, { status: f.status.value, resolution: f.resolution.value.trim() })); toast("Saved", "ok"); ctx.rerender(); }
      catch (e) { toast(e.message, "error"); }
    });
  }));
}

export async function adminModerationView(el, ctx) {
  const tab = ctx.query.get("tab") || "reports";
  const status = ctx.query.has("status") ? ctx.query.get("status") : "OPEN";
  mount(el, html`${pageHead("Reports & support")}${loadingBlock()}`);
  const head = html`${pageHead("Reports & support", "People reported by other users, and customers' support chats.")}
    <nav class="tabs"><a class="tabs__tab" href="#/admin/moderation?tab=reports" ${tab === "reports" ? html`aria-current="page"` : ""}>User reports</a>
      ${can("admin.support.chat") ? html`<a class="tabs__tab" href="#/admin/moderation?tab=support" ${tab === "support" ? html`aria-current="page"` : ""}>Support chats</a>` : ""}</nav>`;
  if (tab === "support") {
    const chats = await api.get("admin/support/chats/");
    mount(el, html`${head}<section class="panel">${chats.length ? html`<ul class="convs">${chats.map((c) => html`<li><a class="conv" href="#/chat/${c.id}">
      <span class="conv__title">${c.customer}</span><span class="conv__last">${c.last_message}</span><span class="conv__meta">${c.last_message_at ? formatDateTime(c.last_message_at) : ""}</span></a></li>`)}</ul>`
      : emptyState("No support chats", "Customers' messages to support appear here.")}</section>`);
    return;
  }
  const data = await api.get("admin/moderation/reports/", { status });
  const tabs = [["OPEN", "Open"], ["WARNED", "Warned"], ["ACTIONED", "Actioned"], ["DISMISSED", "Dismissed"]];
  mount(el, html`${head}
    <nav class="tabs tabs--sub">${tabs.map(([k, l]) => html`<a class="tabs__tab" href="#/admin/moderation?status=${k}" ${k === status ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    <section class="panel">${data.results.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Reported</th><th scope="col">Reason</th><th scope="col">By</th><th scope="col">When</th><th scope="col">Status</th><th></th></tr></thead>
      <tbody>${data.results.map((r) => html`<tr><td>${r.reported.name}<span class="sub">${r.reported.email} · ${r.reported.total} report(s)${r.reported.is_frozen ? " · frozen" : ""}</span></td>
        <td>${r.reason_label}<span class="sub">${r.details.slice(0, 80)}</span></td><td>${r.reporter.name}</td><td class="nowrap">${formatDateTime(r.created_at)}</td>
        <td>${statusTag(r.status, r.status_label)}</td><td><button class="btn btn--quiet btn--small" data-open="${r.id}">Review</button></td></tr>`)}</tbody></table>`
      : emptyState("Nothing here", "Reports from users appear here.")}</section>`);
  $$("[data-open]", el).forEach((b) => b.addEventListener("click", async () => {
    const r = await api.get(`admin/moderation/reports/${b.dataset.open}/`);
    const panel = openDrawer(html`<h2 id="drawer-title">${r.reported.name}: ${r.reason_label}</h2>
      <p class="muted">Reported by ${r.reporter.name} on ${formatDateTime(r.created_at)}</p>
      <blockquote class="quote-block">${r.details}</blockquote>
      ${r.context ? html`<h3>Conversation</h3><ol class="msgs msgs--compact">${r.context.map((m) => html`<li class="msg ${m.reported ? "msg--flagged" : ""}"><p class="msg__who">${m.sender}</p><p class="msg__body">${m.body}</p><time>${formatDateTime(m.at)}</time></li>`)}</ol>` : ""}
      <p class="small">${r.reported.total} report(s) about this person, ${r.reported.actioned} acted on.</p>
      ${r.status === "OPEN" && can("admin.moderation.manage") ? html`<form class="form" id="resolve-form">
        ${field("decision", "Action", html`<select name="decision"><option value="DISMISS">Dismiss (no breach)</option><option value="WARN">Warn the user</option>
          ${r.message ? html`<option value="HIDE_MESSAGE">Hide the message</option>` : ""}${can("admin.accounts.freeze") ? html`<option value="FREEZE">Freeze the account</option>` : ""}</select>`)}
        ${field("note", "Note (a warning is sent to the user; otherwise kept in the audit trail)", html`<textarea name="note" rows="3"></textarea>`)}
        <button class="btn" type="submit">Save decision</button></form>` : html`<p>Outcome: ${r.status_label}${r.resolution ? ` — ${r.resolution}` : ""}</p>`}`);
    $("#resolve-form", panel)?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.currentTarget;
      try { await busy(f.querySelector("button"), "Saving…", () => api.post(`admin/moderation/reports/${r.id}/`, { action: f.decision.value, note: f.note.value.trim() })); toast("Decision saved", "ok"); ctx.rerender(); }
      catch (e) { toast(e.message, "error"); }
    });
  }));
}
