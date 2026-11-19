// Staff: extension requests, overdue and defaulted loans, guarantor claims.
import { api } from "../api.js";
import { $$, formatDate, html, mount, toast } from "../ui.js";
import { busy, emptyState, loadingBlock, pageHead } from "./common.js";
import { pager } from "./pager.js";
import { money, statusTag } from "./shared.js";

export async function adminExtensionsView(el, ctx) {
  const status = ctx.query.get("status") || "REQUESTED";
  const page = ctx.query.get("page") || "1";
  mount(el, html`${pageHead("Extensions")}${loadingBlock()}`);
  const data = await api.get("admin/extensions/", { status, page });
  const tabs = [["REQUESTED", "To review"], ["AWAITING_CONSENT", "With investors"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"]];
  mount(el, html`${pageHead("Extensions", "Borrowers asking for more time. Approving sends it to investors if the rules need their consent.")}
    <nav class="tabs">${tabs.map(([k, l]) => html`<a class="tabs__tab" href="#/admin/extensions?status=${k}" ${k === status ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    ${data.results.length ? html`${data.results.map((e) => html`<section class="panel">
      <div class="panel__head"><h2><a class="linkish" href="#/admin/loans/${e.loan_id}">${e.loan}</a> · ${e.borrower}</h2>${statusTag(e.status, e.status_label)}</div>
      <p>${e.days} more days: “${e.reason}”</p>
      <table class="kv"><tr><th scope="row">Cost to the borrower</th><td>${money(e.extension_interest)} interest + ${money(e.extension_fee)} fee on ${money(e.remaining_principal)} remaining</td></tr>
        <tr><th scope="row">Context</th><td>${e.after_missed_payment ? "Asked after a missed payment" : "Asked before a payment was missed"} · ${e.extensions_so_far} earlier extension(s) · trust ${e.trust_score ?? "–"}</td></tr>
        <tr><th scope="row">Investor consent</th><td>${e.consent_mode}${e.consent_deadline ? ` until ${formatDate(e.consent_deadline)}` : ""} · ${e.votes.agree} agree, ${e.votes.object} object</td></tr>
        ${e.decision_reason ? html`<tr><th scope="row">Decision</th><td>${e.decision_reason}${e.reviewed_by ? ` (${e.reviewed_by})` : ""}</td></tr>` : ""}</table>
      ${e.status === "REQUESTED" ? html`<p><button class="btn btn--small" data-approve="${e.id}">Approve</button> <button class="btn btn--quiet btn--small btn--danger-text" data-reject="${e.id}">Reject</button></p>` : ""}
    </section>`)}${pager(data, Number(page))}` : html`<section class="panel">${emptyState("Nothing here", "Extension requests appear here.")}</section>`}`);
  const decide = (b, approve) => {
    const reason = window.prompt(approve ? "Note for the record:" : "Reason (the borrower sees this):", "");
    if (!reason) return;
    busy(b, "…", () => api.post(`admin/extensions/${b.dataset.approve || b.dataset.reject}/decision/`, { approve, reason }))
      .then(() => { toast("Done", "ok"); ctx.rerender(); }).catch((e) => toast(e.message, "error"));
  };
  $$("[data-approve]", el).forEach((b) => b.addEventListener("click", () => decide(b, true)));
  $$("[data-reject]", el).forEach((b) => b.addEventListener("click", () => decide(b, false)));
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/extensions", { status, page: b.dataset.page })));
}

export async function adminDefaultsView(el, ctx) {
  mount(el, html`${pageHead("Arrears & defaults")}${loadingBlock()}`);
  const d = await api.get("admin/defaults/");
  mount(el, html`${pageHead("Arrears & defaults", "Overdue and defaulted loans, and what guarantors owe on defaulted loans. Guarantor wallets are checked daily and anything available is passed to investors.")}
    <section class="panel"><h2>Loans</h2>${d.loans.length ? html`<table class="table table--plain">
      <thead><tr><th scope="col">Loan</th><th scope="col">Borrower</th><th scope="col">Status</th><th scope="col" class="num">Days overdue</th><th scope="col" class="num">Owed</th><th scope="col" class="num">Late fees</th></tr></thead>
      <tbody>${d.loans.map((l) => html`<tr><td><a class="linkish" href="#/admin/loans/${l.id}">${l.reference}</a></td><td>${l.borrower}<span class="sub">${l.borrower_email}</span></td>
        <td>${statusTag(l.status, l.status_label)}</td><td class="num">${l.days_overdue ?? "–"}</td><td class="num">${money(l.outstanding)}</td><td class="num">${money(l.late_fees)}</td></tr>`)}</tbody></table>`
      : emptyState("No arrears", "Overdue loans appear here.")}</section>
    <section class="panel"><h2>Guarantor claims</h2>${d.claims.length ? html`<table class="table table--plain">
      <thead><tr><th scope="col">Loan</th><th scope="col">Guarantor</th><th scope="col" class="num">Claim</th><th scope="col" class="num">Recovered</th><th scope="col">Status</th><th></th></tr></thead>
      <tbody>${d.claims.map((c) => html`<tr><td>${c.loan}</td><td>${c.guarantor}<span class="sub">${c.guarantor_email}</span></td>
        <td class="num">${money(c.amount)}</td><td class="num">${money(c.recovered)}</td><td>${statusTag(c.status, c.status_label)}</td>
        <td class="nowrap">${["OPEN", "PARTLY_RECOVERED"].includes(c.status) ? html`<button class="btn btn--small" data-collect="${c.id}">Collect now</button>
          <button class="btn btn--quiet btn--small btn--danger-text" data-writeoff="${c.id}">Write off</button>` : ""}</td></tr>`)}</tbody></table>`
      : emptyState("No claims", "Claims are opened automatically when a guaranteed loan defaults.")}</section>`);
  const run = (b, body, msg) => busy(b, "…", () => api.post(`admin/claims/${b.dataset.collect || b.dataset.writeoff}/`, body))
    .then(() => { toast(msg, "ok"); ctx.rerender(); }).catch((e) => toast(e.message, "error"));
  $$("[data-collect]", el).forEach((b) => b.addEventListener("click", () => run(b, { action: "COLLECT" }, "Collected what was available")));
  $$("[data-writeoff]", el).forEach((b) => b.addEventListener("click", () => {
    const reason = window.prompt("Why is this claim being written off? (recorded in the audit trail)", "");
    if (reason) run(b, { action: "WRITE_OFF", reason }, "Claim written off");
  }));
}
