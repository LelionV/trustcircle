// Staff: ledger & reconciliation, payments, and withdrawal approvals.
import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, emptyState, loadingBlock, pageHead } from "./common.js";
import { pager } from "./pager.js";
import { money, stats, statusTag } from "./shared.js";

const TABS = [["reconcile", "Reconciliation", "admin.reconciliation.run"], ["revenue", "Revenue", "admin.revenue.view"],
  ["ledger", "Ledger", "admin.ledger.view"], ["payments", "Payments", "admin.wallets.view"]];

export async function adminFinanceView(el, ctx) {
  const allowed = TABS.filter(([, , p]) => can(p));
  const tab = ctx.query.get("tab") || allowed[0]?.[0];
  mount(el, html`${pageHead("Ledger & wallets")}
    <nav class="tabs" aria-label="Finance">${allowed.map(([k, l]) => html`<a class="tabs__tab" href="#/admin/finance?tab=${k}" ${k === tab ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    <div id="fin-body">${loadingBlock()}</div>`);
  const body = $("#fin-body", el);
  await ({ reconcile: reconcileTab, revenue: revenueTab, ledger: ledgerTab, payments: paymentsTab })[tab](body, ctx);
}

async function reconcileTab(host, ctx) {
  const r = await api.get("admin/finance/reconcile/");
  mount(host, html`
    <p class="notice ${r.ok ? "notice--success" : "notice--error"}">${r.ok ? "The books balance." : `${r.problems.length} problem(s) found.`} Checked ${formatDateTime(r.checked_at)}.</p>
    ${stats([["Money held (M-Pesa, bank, sandbox)", money(r.money_held)], ["Owed to customers", money(r.owed_to_users)],
      ["Platform revenue", money(r.revenue)], ["Journal entries", String(r.entries)]])}
    <section class="panel"><h2>Checks</h2>
      <ul><li>Every journal entry's debits equal its credits</li><li>Every account's balance equals the sum of its lines</li>
      <li>Money held equals what's owed to customers plus revenue</li></ul>
      ${r.problems.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Check</th><th scope="col">Detail</th></tr></thead>
        <tbody>${r.problems.map((p) => html`<tr><td>${p.check}</td><td>${p.detail}</td></tr>`)}</tbody></table>` : ""}
      <button class="btn btn--quiet" id="again">Run again</button></section>`);
  $("#again", host).addEventListener("click", () => ctx.rerender());
}

async function revenueTab(host, ctx) {
  const start = ctx.query.get("start") || "";
  const end = ctx.query.get("end") || "";
  const r = await api.get("admin/finance/revenue/", { start, end });
  mount(host, html`<section class="panel"><h2>Revenue by category</h2>
    <form class="filters" id="period"><label>From <input type="date" name="start" value="${start}"></label><label>To <input type="date" name="end" value="${end}"></label><button class="btn btn--quiet">Show</button></form>
    <table class="table table--plain"><tbody>${Object.values(r.categories).map((c) => html`<tr><td>${c.label}</td><td class="num">${money(c.amount)}</td></tr>`)}
      <tr><th scope="row">Total</th><td class="num"><strong>${money(r.total)}</strong></td></tr></tbody></table></section>`);
  $("#period", host).addEventListener("submit", (ev) => { ev.preventDefault(); ctx.navigate("/admin/finance", { tab: "revenue", start: ev.currentTarget.start.value, end: ev.currentTarget.end.value }); });
}

async function ledgerTab(host, ctx) {
  const page = ctx.query.get("page") || "1";
  const search = ctx.query.get("search") || "";
  const data = await api.get("admin/finance/ledger/", { page, search });
  mount(host, html`<form class="filters" id="ledger-search"><label class="field field--search"><input type="search" name="search" value="${search}" placeholder="Entry or M-Pesa reference"></label><button class="btn btn--quiet">Search</button></form>
    ${data.results.length ? html`${data.results.map((e) => html`<section class="panel entry">
      <p><strong>${e.reference}</strong> · ${e.kind_label} · ${formatDateTime(e.created_at)} · by ${e.by}${e.loan ? ` · loan ${e.loan}` : ""}${e.external_reference ? ` · ${e.external_reference}` : ""}</p>
      <p class="small muted">${e.description}</p>
      <table class="table table--plain table--num"><thead><tr><th scope="col">Account</th><th scope="col">Owner</th><th scope="col">Debit</th><th scope="col">Credit</th><th scope="col">Memo</th></tr></thead>
      <tbody>${e.lines.map((l) => html`<tr><td>${l.account}</td><td>${l.owner}</td><td>${l.side === "DEBIT" ? money(l.amount) : ""}</td><td>${l.side === "CREDIT" ? money(l.amount) : ""}</td><td class="small">${l.memo}</td></tr>`)}</tbody></table></section>`)}
      ${pager(data, Number(page))}` : emptyState("No entries", "Ledger entries appear as money moves.")}`);
  $("#ledger-search", host).addEventListener("submit", (ev) => { ev.preventDefault(); ctx.navigate("/admin/finance", { tab: "ledger", search: ev.currentTarget.search.value.trim() }); });
  $$("[data-page]", host).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/finance", { tab: "ledger", search, page: b.dataset.page })));
}

function paymentsTable(data, decide) {
  return html`<div class="table-wrap table-wrap--flat"><table class="table table--plain">
    <thead><tr><th scope="col">Customer</th><th scope="col">What</th><th scope="col" class="num">Amount</th><th scope="col" class="num">Fee</th><th scope="col">Status</th><th scope="col">When</th>${decide ? html`<th></th>` : ""}</tr></thead>
    <tbody>${data.results.map((p) => html`<tr>
      <td>${p.user.name}<span class="sub">${p.user.email}</span></td>
      <td>${p.purpose_label}<span class="sub">${p.provider_label}${p.phone_number ? ` · ${p.phone_number}` : ""}${p.provider_reference ? ` · ${p.provider_reference}` : ""}</span></td>
      <td class="num">${money(p.amount)}</td><td class="num">${money(p.fee)}</td>
      <td>${statusTag(p.status, p.status_label)}${p.failure_reason ? html`<span class="sub">${p.failure_reason}</span>` : ""}</td>
      <td class="nowrap">${formatDateTime(p.created_at)}</td>
      ${decide ? html`<td class="nowrap">${p.status === "AWAITING_APPROVAL" ? html`<button class="btn btn--small" data-approve="${p.id}">Approve</button>
        <button class="btn btn--quiet btn--small btn--danger-text" data-reject="${p.id}">Reject</button>` : ""}</td>` : ""}</tr>`)}</tbody></table></div>`;
}

async function paymentsTab(host, ctx) {
  const page = ctx.query.get("page") || "1";
  const status = ctx.query.get("status") || "";
  const data = await api.get("admin/payments/", { page, status });
  mount(host, html`<form class="filters"><select id="pay-status" aria-label="Status">${[["", "All"], ["PENDING", "Waiting for confirmation"], ["AWAITING_APPROVAL", "Waiting for approval"], ["PROCESSING", "Being paid out"], ["SUCCEEDED", "Completed"], ["FAILED", "Failed"]].map(([v, l]) => html`<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`)}</select></form>
    ${data.results.length ? html`${paymentsTable(data, false)}${pager(data, Number(page))}` : emptyState("No payments", "Deposits and withdrawals appear here.")}`);
  $("#pay-status", host).addEventListener("change", (ev) => ctx.navigate("/admin/finance", { tab: "payments", status: ev.target.value }));
  $$("[data-page]", host).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/finance", { tab: "payments", status, page: b.dataset.page })));
}

export async function adminWithdrawalsView(el, ctx) {
  mount(el, html`${pageHead("Withdrawals")}${loadingBlock()}`);
  const data = await api.get("admin/payments/", { status: "AWAITING_APPROVAL", direction: "OUT", page_size: 100 });
  mount(el, html`${pageHead("Withdrawals", "Withdrawals at or above the approval limit wait here. The customer's money is already set aside; rejecting returns it with the fee.")}
    <section class="panel">${data.results.length ? paymentsTable(data, true) : emptyState("Nothing waiting", "Large withdrawals appear here for a second check.")}</section>`);
  const decide = async (btn, body, msg) => { try { await busy(btn, "…", () => api.post(`admin/payments/${btn.dataset.approve || btn.dataset.reject}/decision/`, body)); toast(msg, "ok"); ctx.rerender(); } catch (e) { toast(e.message, "error"); } };
  $$("[data-approve]", el).forEach((b) => b.addEventListener("click", () => { if (window.confirm("Approve and send this payout?")) decide(b, { approve: true }, "Approved; payout started"); }));
  $$("[data-reject]", el).forEach((b) => b.addEventListener("click", () => {
    const reason = window.prompt("Reason (the customer sees this):", "");
    if (reason) decide(b, { approve: false, reason }, "Rejected; money returned");
  }));
}
