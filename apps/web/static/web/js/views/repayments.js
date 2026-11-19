import { api } from "../api.js";
import { $$, formatDate, formatDateTime, html, mount } from "../ui.js";
import { emptyState, loadingBlock, loanTag, pageHead } from "./common.js";
import { pager } from "./pager.js";
import { money } from "./shared.js";

export async function repaymentsView(el, ctx) {
  const page = ctx.query.get("page") || "1";
  mount(el, html`${pageHead("Repayments")}${loadingBlock()}`);
  const [loans, history] = await Promise.all([api.get("loans/"), api.get("repayments/", { page })]);
  const live = loans.filter((l) => ["ACTIVE", "OVERDUE", "DEFAULTED"].includes(l.status));
  mount(el, html`
    ${pageHead("Repayments", "Paying on or before the due date raises your trust score; paying a whole loan off early earns a bonus.")}
    <section class="panel"><h2>Loans you're repaying</h2>
      ${live.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Loan</th><th scope="col">Next payment</th><th scope="col" class="num">Still owed</th><th scope="col">Status</th><th></th></tr></thead>
        <tbody>${live.map((l) => html`<tr><td>${l.reference}</td>
          <td>${l.outstanding?.next_due_date ? html`${money(l.outstanding.next_due_amount)} <span class="sub">due ${formatDate(l.outstanding.next_due_date)}</span>` : "–"}</td>
          <td class="num">${money(l.outstanding?.total)}</td><td>${loanTag(l.status, l.status_label)}</td>
          <td><a class="btn btn--small" href="#/loans/${l.id}">Pay or extend</a></td></tr>`)}</tbody></table>`
      : emptyState("Nothing to repay", "Loans that have been paid out appear here.")}</section>
    <section class="panel"><h2>Payments made</h2>
      ${history.results.length ? html`<table class="table table--plain"><thead><tr><th scope="col">When</th><th scope="col">Loan</th><th scope="col" class="num">Paid</th><th scope="col" class="num">Principal</th><th scope="col" class="num">Interest</th><th scope="col" class="num">Fees</th></tr></thead>
        <tbody>${history.results.map((r) => html`<tr><td class="nowrap">${formatDateTime(r.created_at)}</td><td><a class="linkish" href="#/loans/${r.loan_id}">${r.loan}</a></td>
          <td class="num">${money(r.amount)}</td><td class="num">${money(r.principal)}</td>
          <td class="num">${money((Number(r.interest) + Number(r.extension_interest)).toFixed(2))}</td>
          <td class="num">${money((Number(r.late_fee) + Number(r.extension_fee)).toFixed(2))}</td></tr>`)}</tbody></table>${pager(history, Number(page))}`
      : html`<p class="muted">No payments yet.</p>`}</section>`);
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/repayments", { page: b.dataset.page })));
}
