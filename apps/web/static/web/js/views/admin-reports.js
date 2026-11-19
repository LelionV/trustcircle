import { api } from "../api.js";
import { $, $$, html, mount } from "../ui.js";
import { loadingBlock, pageHead } from "./common.js";
import { download, money, stats } from "./shared.js";

const STATUS_ORDER = ["PUBLISHED", "PARTIALLY_FUNDED", "GUARANTOR_PENDING", "READY_FOR_DISBURSEMENT", "ACTIVE", "OVERDUE", "DEFAULTED", "COMPLETED", "CANCELLED", "REJECTED"];

export async function adminReportsView(el, ctx) {
  const start = ctx.query.get("start") || "";
  const end = ctx.query.get("end") || "";
  mount(el, html`${pageHead("Reports")}${loadingBlock()}`);
  const r = await api.get("admin/reports/", { start, end });
  const p = r.portfolio;
  const f = r.finance;
  mount(el, html`
    ${pageHead("Reports", "Lending and financial figures, calculated from the ledger and the loan book.")}
    <h2>Loan book</h2>
    ${stats([
      ["Lent out so far", money(p.total_disbursed), `${p.loans_disbursed} loans`],
      ["Principal still owed", money(p.outstanding_principal)],
      ["Portfolio at risk (30+ days)", money(p.par_30), `${p.par_30_percent}% of what's owed`],
      ["Default rate", `${p.default_rate_percent}%`, "Of loans that have finished"],
      ["Repaid", money(p.repaid_total), `${money(p.repaid_interest)} of it interest`],
      ["Waiting for funding", money(p.funding_needed), `${p.open_for_funding} loans open`],
    ])}
    <section class="panel"><h2>Loans by status</h2><table class="table table--plain"><tbody>
      ${STATUS_ORDER.filter((s) => p.loans_by_status[s]).map((s) => html`<tr><td>${s.replace(/_/g, " ").toLowerCase()}</td><td class="num">${p.loans_by_status[s]}</td></tr>`)}</tbody></table></section>
    <h2>Money</h2>
    <form class="filters" id="period"><label>From <input type="date" name="start" value="${start}"></label><label>To <input type="date" name="end" value="${end}"></label><button class="btn btn--quiet">Apply</button></form>
    ${stats([
      ["Deposits", money(f.deposits), `${f.deposit_count} payments`],
      ["Withdrawals", money(f.withdrawals), `${f.withdrawal_count} payouts`],
      ["Revenue", money(f.revenue_total)],
      ["Withdrawals awaiting approval", String(f.withdrawals_awaiting_approval)],
    ])}
    <section class="panel"><h2>Revenue by category</h2><table class="table table--plain"><tbody>
      ${Object.values(f.revenue).map((c) => html`<tr><td>${c.label}</td><td class="num">${money(c.amount)}</td></tr>`)}</tbody></table></section>
    <section class="panel"><h2>Downloads (CSV)</h2><p class="panel__text">Uses the period above where it applies. Every download is recorded in the audit trail.</p>
      <p>${r.exports.map((x) => html`<button class="btn btn--quiet" data-export="${x.key}">${x.label}</button> `)}</p></section>`);
  $("#period", el).addEventListener("submit", (ev) => { ev.preventDefault(); ctx.navigate("/admin/reports", { start: ev.currentTarget.start.value, end: ev.currentTarget.end.value }); });
  $$("[data-export]", el).forEach((b) => b.addEventListener("click", () => {
    const qs = new URLSearchParams(Object.entries({ start, end }).filter(([, v]) => v));
    download(`/api/v1/admin/reports/${b.dataset.export}.csv${[...qs].length ? `?${qs}` : ""}`, `p2plend-${b.dataset.export}.csv`);
  }));
}
