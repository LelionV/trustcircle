import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDate, formatDateTime, formatMoney, html, mount, toast } from "../ui.js";
import { scheduleTable } from "./apply.js";
import { busy, CONFIDENCE, emptyState, field, kycTag, loadingBlock, loanTag, pageHead, riskTag, showFieldErrors } from "./common.js";
import { documentLinks, wireDocuments } from "./documents.js";
import { pager } from "./pager.js";
import { money, rateText, statusTag } from "./shared.js";
import { componentRows } from "./trust.js";

const PRE_PAYOUT = ["PUBLISHED", "PARTIALLY_FUNDED", "FULLY_FUNDED", "GUARANTOR_PENDING", "READY_FOR_DISBURSEMENT"];

const TABS = [["SUBMITTED", "New"], ["UNDER_REVIEW", "In review"], ["APPROVED", "Approved"], ["PUBLISHED", "Open for funding"],
  ["GUARANTOR_PENDING", "Waiting for guarantor"], ["READY_FOR_DISBURSEMENT", "Ready to pay out"], ["ACTIVE", "Active"],
  ["OVERDUE", "Overdue"], ["DEFAULTED", "Defaulted"], ["REJECTED", "Rejected"], ["", "All"]];

export async function adminLoanListView(el, ctx) {
  const status = ctx.query.has("status") ? ctx.query.get("status") : "SUBMITTED";
  const search = ctx.query.get("search") || "";
  const page = ctx.query.get("page") || "1";
  mount(el, html`${pageHead("Loan review")}${loadingBlock()}`);
  const data = await api.get("admin/loans/", { status, search, page });
  mount(el, html`
    ${pageHead("Loan review", "Applications in the order they arrived.")}
    <nav class="tabs" aria-label="Status">${TABS.map(([v, l]) => html`<a class="tabs__tab" href="#/admin/loans?status=${v}" ${v === status ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    <form class="filters" id="loan-search" role="search">
      <label class="field field--search"><span class="sr-only">Search</span><input type="search" name="search" value="${search}" placeholder="Reference, borrower name or email"></label>
      <button class="btn btn--quiet" type="submit">Search</button>
    </form>
    ${data.results.length ? html`<div class="table-wrap"><table class="table">
      <thead><tr><th scope="col">Loan</th><th scope="col">Borrower</th><th scope="col">Amount</th><th scope="col">Trust</th><th scope="col">Risk</th><th scope="col">Rate</th><th scope="col">Status</th><th scope="col">Submitted</th></tr></thead>
      <tbody>${data.results.map((l) => html`<tr>
        <td><a class="linkish" href="#/admin/loans/${l.id}">${l.reference}</a></td>
        <td>${l.borrower_name}<span class="sub">${l.borrower_email}</span></td>
        <td class="nowrap">${formatMoney(l.amount)}<span class="sub">${l.term_months} months</span></td>
        <td>${l.trust_score_snapshot ?? "–"}</td>
        <td>${riskTag(l.risk_class_snapshot)}</td>
        <td>${l.annual_rate ? `${l.annual_rate}%` : l.requires_manual_pricing ? html`<span class="tag tag--warn">Set manually</span>` : "–"}</td>
        <td>${loanTag(l.status, l.status_label)}</td>
        <td class="nowrap">${l.submitted_at ? formatDate(l.submitted_at) : "–"}</td>
      </tr>`)}</tbody></table></div>${pager(data, Number(page))}`
    : html`<section class="panel">${emptyState("No loans here", "Applications appear here when borrowers submit them.")}</section>`}`);
  $("#loan-search", el).addEventListener("submit", (ev) => {
    ev.preventDefault();
    ctx.navigate("/admin/loans", { status, search: ev.currentTarget.search.value.trim() });
  });
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/loans", { status, search, page: b.dataset.page })));
}

export async function adminLoanDetailView(el, ctx) {
  mount(el, html`${pageHead("Loan review")}${loadingBlock()}`);
  const l = await api.get(`admin/loans/${ctx.params.id}/`);
  const b = l.borrower;
  const p = b.profile || {};
  const decide = can(["admin.loans.approve", "admin.loans.disburse", "admin.defaults.manage"]);
  const inReview = ["SUBMITTED", "UNDER_REVIEW"].includes(l.status);
  const income = Number(l.monthly_income || 0);
  const commitments = Number(l.monthly_obligations || 0);
  const installmentShare = income > commitments && l.installment_amount
    ? Math.round((Number(l.installment_amount) * (l.repayment_frequency === "WEEKLY" ? 52 / 12 : l.repayment_frequency === "BIWEEKLY" ? 26 / 12 : 1)) * 100 / (income - commitments))
    : null;

  mount(el, html`
    <a class="back" href="#/admin/loans">Loan review</a>
    <header class="page-head page-head--row">
      <div><h1>${l.reference}</h1><p class="lead">${formatMoney(l.amount)} over ${l.term_months} months for ${l.purpose_label.toLowerCase()}</p></div>
      ${loanTag(l.status, l.status_label)}
    </header>
    <div class="columns">
      <section class="panel">
        <h2>Borrower</h2>
        <table class="kv">
          <tr><th scope="row">Name</th><td><a href="#/admin/users?search=${encodeURIComponent(b.email)}">${b.full_name}</a><span class="sub">${b.email}</span></td></tr>
          <tr><th scope="row">Identity</th><td>${kycTag(b.kyc_status)}</td></tr>
          <tr><th scope="row">Trust score</th><td>${b.trust?.score ?? "–"} <span class="sub">${CONFIDENCE[b.trust?.confidence] || ""} confidence, ${b.trust?.bracket?.label || "no"} bracket</span></td></tr>
          <tr><th scope="row">Risk</th><td>${riskTag(b.risk?.classification)} ${b.risk?.is_assessed ? `score ${b.risk.score}` : ""}${b.risk?.is_overridden ? html` <span class="tag tag--warn">Overridden</span>` : ""}</td></tr>
          <tr><th scope="row">Income</th><td>${l.monthly_income ? formatMoney(l.monthly_income) : "–"} a month ${p.income_verified ? html`<span class="tag tag--ok">Verified</span>` : html`<span class="tag tag--warn">Not verified</span>`}</td></tr>
          <tr><th scope="row">Commitments</th><td>${formatMoney(l.monthly_obligations || "0")} a month</td></tr>
          <tr><th scope="row">This loan's repayments</th><td>${installmentShare === null ? "–" : `${installmentShare}% of income left after commitments (limit ${Number(l.product.max_installment_share)}%)`}</td></tr>
          <tr><th scope="row">Employment</th><td>${p.employment_status_label || "–"}${p.employer_name ? `, ${p.employer_name}` : ""}</td></tr>
          <tr><th scope="row">Account</th><td>${b.is_frozen ? html`<span class="tag tag--warn">Frozen</span>` : "Active"}, since ${formatDate(b.date_joined)}</td></tr>
        </table>
      </section>
      <section class="panel">
        <h2>Loan</h2>
        <table class="kv">
          <tr><th scope="row">Product</th><td>${l.product.name}</td></tr>
          <tr><th scope="row">Funding</th><td>${l.funding_mode_label}${l.funding ? html`<span class="sub">${l.funding.percent}% funded by ${l.funding.investors} investor(s)</span>` : ""}</td></tr>
          <tr><th scope="row">Rate</th><td>${l.annual_rate ? rateText(l.annual_rate, l.rate_basis) : l.funding_mode === "OFFERS" ? "Set by investors' offers" : html`<span class="tag tag--warn">To be set manually</span>`} ${l.bracket_label && l.funding_mode === "STANDARD" ? `(${l.bracket_label} bracket)` : ""}</td></tr>
          <tr><th scope="row">Method</th><td>${l.interest_method_label}</td></tr>
          <tr><th scope="row">Repayments</th><td>${l.installment_amount ? `${formatMoney(l.installment_amount)} ${l.frequency_label.toLowerCase()}, ${l.installment_count} payments` : l.frequency_label}</td></tr>
          <tr><th scope="row">Total interest</th><td>${l.total_interest ? formatMoney(l.total_interest) : "–"}</td></tr>
          <tr><th scope="row">Guarantor</th><td>${l.guarantor ? html`${l.guarantor.name} ${statusTag(l.guarantor.status, l.guarantor.status_label)}<span class="sub">${l.guarantor.email}${Number(l.guarantor.locked_interest) > 0 ? ` · ${money(l.guarantor.locked_interest)} locked` : ""}</span>` : "None (open offers)"}</td></tr>
          <tr><th scope="row">Agreement</th><td>${l.agreement ? (l.agreement.accepted_at ? `Version ${l.agreement.version} accepted ${formatDate(l.agreement.accepted_at)}` : `Version ${l.agreement.version}, not accepted yet`) : "Not issued yet"}</td></tr>
          <tr><th scope="row">Purpose</th><td>${l.purpose_label}${l.purpose_details ? html`<span class="sub">${l.purpose_details}</span>` : ""}</td></tr>
          <tr><th scope="row">Documents</th><td>${documentLinks(l.documents)}</td></tr>
          ${l.reviewed_by_email ? html`<tr><th scope="row">Reviewer</th><td>${l.reviewed_by_email}</td></tr>` : ""}
        </table>
        <p class="small muted">Trust score, risk and rate are taken again at approval and then locked for the life of the loan.</p>
      </section>
    </div>

    ${decide ? html`<section class="panel" id="actions">
      <h2>Decision</h2>
      ${l.status === "SUBMITTED" && can("admin.loans.approve") ? html`<p><button class="btn btn--quiet" type="button" id="start-review">Start review</button> <span class="small muted">Marks the application as yours to review.</span></p>` : ""}
      ${inReview && can("admin.loans.approve") ? html`<div class="columns">
        <form id="approve-form" class="form" novalidate>
          ${l.requires_manual_pricing && l.funding_mode === "STANDARD" ? field("annual_rate", `Rate (% ${({ MONTHLY: "a month", ANNUAL: "a year", PER_LOAN: "for the loan" })[l.rate_basis] || "a month"}) for this borrower`, html`<input name="annual_rate" inputmode="decimal" required>`,
            "Their trust bracket has no automatic rate.") : ""}
          ${field("reason", "Approval note", html`<textarea name="reason" rows="2" maxlength="1000" placeholder="e.g. Verified income covers repayments comfortably."></textarea>`)}
          <button class="btn" type="submit">Approve loan</button>
        </form>
        <form id="reject-form" class="form form--danger" novalidate>
          ${field("reason", "Reason for rejecting (the borrower sees this)", html`<textarea name="reason" rows="2" maxlength="1000"></textarea>`)}
          <button class="btn btn--danger" type="submit">Reject</button>
        </form></div>` : ""}
      ${l.status === "APPROVED" && can("admin.loans.approve") ? html`<p><button class="btn" type="button" id="publish">Open for funding</button>
        <span class="small muted">Shows the loan to investors for ${l.product.funding_period_days} days.</span></p>` : ""}
      ${l.status === "READY_FOR_DISBURSEMENT" && can("admin.loans.disburse") ? html`<p>${l.agreement?.accepted_at
        ? html`<button class="btn" type="button" id="disburse">Pay ${formatMoney(l.amount)} to the borrower's wallet</button> <span class="small muted">Moves investors' committed money to the borrower and starts the schedule from today.</span>`
        : html`<span class="muted">Waiting for the borrower to accept the agreement before pay-out.</span>`}</p>` : ""}
      ${PRE_PAYOUT.includes(l.status) && can("admin.loans.approve") ? html`<form id="cancel-funding" class="form form--inline form--danger" novalidate>
        ${field("reason", "Cancel before pay-out (investors refunded)", html`<input name="reason" maxlength="500">`)}
        <button class="btn btn--quiet btn--danger-text" type="submit">Cancel loan</button></form>` : ""}
      ${l.status === "OVERDUE" && can("admin.defaults.manage") ? html`<form id="mark-default" class="form form--inline form--danger" novalidate>
        ${field("reason", "Declare in default now", html`<input name="reason" maxlength="500">`)}
        <button class="btn btn--danger" type="submit">Mark as defaulted</button></form>` : ""}
      ${!inReview && !["APPROVED", "READY_FOR_DISBURSEMENT", "OVERDUE", ...PRE_PAYOUT].includes(l.status) ? html`<p class="muted">No action needed at this stage.</p>` : ""}
    </section>` : ""}

    ${b.trust ? html`<section class="panel"><h2>Trust score breakdown</h2>${componentRows(b.trust.breakdown)}</section>` : ""}
    ${b.risk?.is_assessed ? html`<section class="panel"><h2>Risk factors</h2>
      <table class="table table--plain"><thead><tr><th scope="col">Factor</th><th scope="col">Weight</th><th scope="col">Risk</th><th scope="col">Why</th></tr></thead>
      <tbody>${b.risk.factors.map((f) => html`<tr><td>${f.label}</td><td>${f.weight}%</td>
        <td><meter min="0" max="100" low="30" high="60" optimum="0" value="${f.risk}">${f.risk}</meter> ${f.risk}</td><td class="small">${f.detail}</td></tr>`)}</tbody></table>
      ${b.risk.override ? html`<p class="small">Overridden by ${b.risk.override.by}: ${b.risk.override.reason}</p>` : ""}</section>` : ""}

    <section class="panel"><h2>${l.terms_locked ? "Repayment schedule" : "Estimated schedule"}</h2>
      ${l.schedule.length ? scheduleTable(l.schedule, l.terms_locked) : html`<p class="muted">Appears once a rate is set.</p>`}</section>
    <section class="panel"><h2>History</h2>
      <ol class="timeline">${l.history.map((h) => html`<li><p class="timeline__what">${h.to_label}</p>
        <p class="timeline__when">${formatDateTime(h.at)}</p>${h.reason ? html`<p class="timeline__why">${h.reason}</p>` : ""}</li>`)}</ol></section>`);

  wireDocuments(el);
  const act = async (button, label, path, body, message) => {
    try {
      await busy(button, label, () => api.post(path, body));
      toast(message, "ok");
      ctx.rerender();
    } catch (err) {
      const form = button.closest("form");
      if (!form || !showFieldErrors(form, err)) toast(err.message, "error");
    }
  };
  $("#start-review", el)?.addEventListener("click", (ev) => act(ev.currentTarget, "Starting…", `admin/loans/${l.id}/start-review/`, {}, "Review started"));
  $("#publish", el)?.addEventListener("click", (ev) => act(ev.currentTarget, "Opening…", `admin/loans/${l.id}/publish/`, {}, "Loan open for funding"));
  $("#disburse", el)?.addEventListener("click", (ev) => {
    if (window.confirm(`Pay ${formatMoney(l.amount)} to ${b.full_name}'s wallet now?`)) act(ev.currentTarget, "Paying out…", `admin/loans/${l.id}/disburse/`, {}, "Loan paid out");
  });
  for (const [id, path, msg] of [["#cancel-funding", "cancel-funding", "Loan cancelled; investors refunded"], ["#mark-default", "default", "Loan marked as defaulted"]]) {
    const f = $(id, el);
    f?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      if (window.confirm("Are you sure? This can't be undone.")) act(f.querySelector("button"), "…", `admin/loans/${l.id}/${path}/`, { reason: f.reason.value.trim() }, msg);
    });
  }
  const approve = $("#approve-form", el);
  approve?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = { reason: approve.reason.value.trim() };
    if (approve.annual_rate) body.annual_rate = approve.annual_rate.value.trim();
    act(approve.querySelector("button"), "Approving…", `admin/loans/${l.id}/approve/`, body, "Loan approved and terms locked");
  });
  const reject = $("#reject-form", el);
  reject?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    act(reject.querySelector("button"), "Rejecting…", `admin/loans/${l.id}/reject/`, { reason: reject.reason.value.trim() }, "Loan rejected");
  });
}
