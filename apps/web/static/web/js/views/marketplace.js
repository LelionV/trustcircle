import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDate, formatMoney, html, mount, toast } from "../ui.js";
import { busy, CONFIDENCE, emptyState, field, loadingBlock, pageHead, riskTag, showFieldErrors } from "./common.js";
import { closeDrawer, openDrawer } from "./drawer.js";
import { pager } from "./pager.js";
import { reportForm } from "./report.js";
import { idemKey, money, rateText } from "./shared.js";

const MODES = [["STANDARD", "Guaranteed loans"], ["OFFERS", "Open offers (no guarantor)"]];

export async function marketplaceView(el, ctx) {
  const page = ctx.query.get("page") || "1";
  const risk = ctx.query.get("risk") || "";
  const mode = ctx.query.get("mode") || "STANDARD";
  mount(el, html`${pageHead("Loan marketplace")}${loadingBlock()}`);
  const data = await api.get("marketplace/", { page, risk, mode });
  const riskOptions = [["", "Any risk"], ["VERY_LOW", "Very low"], ["LOW", "Low"], ["MEDIUM", "Medium"], ["HIGH", "High"], ["CRITICAL", "Critical"]];

  mount(el, html`
    ${pageHead("Loan marketplace", "Approved loans waiting for investors. Borrowers are shown by first name only.")}
    <nav class="tabs" aria-label="Kind of loan">${MODES.map(([k, l]) => html`<a class="tabs__tab" href="#/marketplace?mode=${k}" ${k === mode ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    ${mode === "OFFERS" ? html`<p class="notice notice--warn">These borrowers have <strong>no guarantor</strong>, so nobody covers the loan if it defaults. You decide the risk: offer an amount and the rate you want. Your offer is held from your wallet until the borrower accepts or declines it, and you can change or withdraw it until then.</p>`
      : html`<p class="notice">Each of these loans has a guarantor who has locked the borrower's interest and covers what's owed if the loan defaults. The rate comes from the borrower's trust score.</p>`}
    <form class="filters" id="mp-filter">
      <label><span class="sr-only">Risk</span><select name="risk">${riskOptions.map(([v, l]) => html`<option value="${v}" ${v === risk ? "selected" : ""}>${l}</option>`)}</select></label>
    </form>
    ${data.results.length ? html`<div class="offers">${data.results.map((l, i) => html`
      <article class="offer">
        <div class="offer__main">
          <p class="offer__amount">${formatMoney(l.amount)}</p>
          <p class="offer__what">${l.purpose_label}, ${l.term_months} month${l.term_months === 1 ? "" : "s"}, repaid ${l.frequency_label.toLowerCase()}</p>
          <p class="offer__who">${l.borrower.display_name}${l.borrower.county ? `, ${l.borrower.county}` : ""}</p>
        </div>
        <dl class="offer__facts">
          ${l.funding_mode === "OFFERS"
            ? html`<div><dt>Offers</dt><dd>${l.offers.open ? `${l.offers.open} open, ${l.offers.lowest_rate}–${l.offers.highest_rate}%` : "None yet"}</dd></div>`
            : html`<div><dt>Rate</dt><dd>${rateText(l.annual_rate, l.rate_basis)}</dd></div>`}
          <div><dt>Trust score</dt><dd>${l.current_trust_score ?? l.trust_score_snapshot}${l.borrower.is_new_borrower ? html` <span class="tag tag--info">New</span>` : ""}</dd></div>
          <div><dt>Risk</dt><dd>${riskTag(l.risk_class_snapshot)}</dd></div>
        </dl>
        <div class="offer__funding">
          <progress max="100" value="${l.funding.percent}">${l.funding.percent}%</progress>
          <p class="small">${l.funding.percent}% funded, ${formatMoney(l.funding.remaining)} to go. Closes ${formatDate(l.funding_expires_at)}</p>
          ${l.mine.offer ? html`<p class="small ok-text">Your offer: ${money(l.mine.offer.amount)} at ${l.mine.offer.rate}%</p>` : ""}
          ${Number(l.mine.invested) > 0 ? html`<p class="small ok-text">You've put in ${money(l.mine.invested)}</p>` : ""}
        </div>
        <button class="btn btn--quiet" type="button" data-loan="${i}">Review</button>
      </article>`)}</div>
      ${pager(data, Number(page))}`
    : html`<section class="panel">${emptyState("No loans open right now", "Approved loans appear here as soon as they open for funding.")}</section>`}`);

  el.querySelector("#mp-filter select").addEventListener("change", (ev) => ctx.navigate("/marketplace", { mode, risk: ev.target.value }));
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/marketplace", { mode, risk, page: b.dataset.page })));
  $$("[data-loan]", el).forEach((b) => b.addEventListener("click", () => showLoan(data.results[Number(b.dataset.loan)], ctx)));
}

function showLoan(l, ctx) {
  const b = l.borrower;
  const offers = l.funding_mode === "OFFERS";
  const blocked = l.mine.is_guarantor;
  const panel = openDrawer(html`
    <h2 id="drawer-title">${formatMoney(l.amount)} ${offers ? "· open offers" : `at ${rateText(l.annual_rate, l.rate_basis)}`}</h2>
    <p class="muted">${l.reference}, ${l.purpose_label.toLowerCase()}</p>
    ${l.purpose_details ? html`<blockquote class="quote-block">${l.purpose_details}</blockquote>` : ""}
    <h3>Borrower</h3>
    <table class="kv">
      <tr><th scope="row">Trust score</th><td><strong>${l.current_trust_score ?? l.trust_score_snapshot}</strong> (confidence: ${CONFIDENCE[l.trust_confidence_snapshot] || "New borrower"})</td></tr>
      <tr><th scope="row">Risk</th><td>${riskTag(l.risk_class_snapshot)} score ${l.risk_score_snapshot}</td></tr>
      <tr><th scope="row">Income</th><td>${b.income_verified ? "Verified by our team" : "Declared, not verified"}</td></tr>
      <tr><th scope="row">Work</th><td>${b.employment_status || "Not given"}</td></tr>
      <tr><th scope="row">History</th><td>${b.is_new_borrower ? "First loan on P2P Lend" : `${b.completed_loans} loans repaid, ${b.on_time_or_early} payments on time or early, ${b.late_payments} late`}</td></tr>
      <tr><th scope="row">Guarantor</th><td>${l.guarantor.status}</td></tr>
    </table>
    <h3>Loan</h3>
    <table class="kv">
      <tr><th scope="row">Term</th><td>${l.term_months} months, ${l.installment_count || "–"} payments ${l.frequency_label.toLowerCase()}</td></tr>
      ${offers ? html`<tr><th scope="row">Open offers</th><td>${l.offers.open ? `${l.offers.open}, from ${l.offers.lowest_rate}% to ${l.offers.highest_rate}%` : "None yet"}</td></tr>`
        : html`<tr><th scope="row">Each payment</th><td>${money(l.installment_amount)}</td></tr>
          <tr><th scope="row">Interest over the loan</th><td>${money(l.total_interest)} (${l.interest_method_label.toLowerCase()})</td></tr>`}
      <tr><th scope="row">Still needed</th><td>${formatMoney(l.funding.remaining)} (closes ${formatDate(l.funding_expires_at)})</td></tr>
    </table>
    <p class="small muted">Each repayment is paid to investors straight away, split by how much each put in${offers ? " and the rate each offered" : ""}.</p>
    ${blocked ? html`<p class="notice">You're this loan's guarantor, so you can't also invest in it.</p>`
      : !can("investments.make") ? "" : offers ? offerForm(l) : investForm(l)}
    <div class="form__actions">
      ${can("chat.use") ? html`<button class="btn btn--quiet" type="button" id="chat-borrower">Message the borrower</button>` : ""}
      ${can("users.report") ? html`<button class="btn btn--quiet btn--danger-text" type="button" id="report-borrower">Report</button>` : ""}
    </div>
    <div id="report-host"></div>`);

  const form = $("#fund-form", panel);
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = form.querySelector("[data-error]");
    err.textContent = "";
    try {
      if (offers && l.mine.offer) {
        await busy(form.querySelector("button[type=submit]"), "Saving…", () => api.patch(`offers/${l.mine.offer.id}/`, { rate: form.rate.value.trim(), message: form.message.value.trim() }));
        toast("Offer updated", "ok");
      } else if (offers) {
        await busy(form.querySelector("button[type=submit]"), "Sending…", () => api.post(`marketplace/${l.id}/offers/`, {
          amount: form.amount.value.trim(), rate: form.rate.value.trim(), message: form.message.value.trim() }));
        toast("Offer sent. The money is held until the borrower answers.", "ok");
      } else {
        if (!window.confirm(`Invest KES ${form.amount.value.trim()} in ${l.reference}? It's committed until the loan is paid out or the funding round closes.`)) return;
        await busy(form.querySelector("button[type=submit]"), "Investing…", () => api.post(`marketplace/${l.id}/invest/`, { amount: form.amount.value.trim(), idempotency_key: idemKey() }));
        toast("Investment committed", "ok");
      }
      closeDrawer();
      ctx.rerender();
    } catch (e) { if (!showFieldErrors(form, e)) err.textContent = e.message; }
  });
  $("#withdraw-offer", panel)?.addEventListener("click", async (ev) => {
    if (!window.confirm("Withdraw your offer? The money goes back to your available balance.")) return;
    try { await busy(ev.currentTarget, "…", () => api.del(`offers/${l.mine.offer.id}/`)); toast("Offer withdrawn", "ok"); closeDrawer(); ctx.rerender(); }
    catch (e) { toast(e.message, "error"); }
  });
  $("#chat-borrower", panel)?.addEventListener("click", async () => {
    try { const c = await api.post("chat/", { loan_id: l.id }); closeDrawer(); ctx.navigate(`/chat/${c.id}`); }
    catch (e) { toast(e.message, "error"); }
  });
  $("#report-borrower", panel)?.addEventListener("click", () => reportForm($("#report-host", panel), { loan_id: l.id }, "the borrower"));
}

function investForm(l) {
  return html`<form class="form" id="fund-form" novalidate>
    <h3>Invest</h3>
    ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" value="${l.funding.remaining}">`, `Up to ${formatMoney(l.funding.remaining)}. Taken from your available balance.`)}
    <p class="form__error" data-error></p>
    <button class="btn btn--wide" type="submit">Invest</button></form>`;
}

function offerForm(l) {
  const mine = l.mine.offer;
  return html`<form class="form" id="fund-form" novalidate>
    <h3>${mine ? "Your offer" : "Make an offer"}</h3>
    <div class="form__row">
      ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" value="${mine ? mine.amount : l.funding.remaining}" ${mine ? "disabled" : ""}>`, mine ? "To change the amount, withdraw and offer again." : `Up to ${formatMoney(l.funding.remaining)}.`)}
      ${field("rate", `Your rate (% ${l.rate_basis === "ANNUAL" ? "a year" : l.rate_basis === "PER_LOAN" ? "for the loan" : "a month"})`, html`<input name="rate" inputmode="decimal" value="${mine ? mine.rate : ""}">`)}
    </div>
    ${field("message", "Message to the borrower (optional)", html`<input name="message" maxlength="500" value="${mine ? mine.message : ""}">`)}
    <p class="form__error" data-error></p>
    <button class="btn btn--wide" type="submit">${mine ? "Update rate" : "Send offer"}</button>
    ${mine ? html`<button class="btn btn--quiet btn--wide" type="button" id="withdraw-offer">Withdraw offer</button>` : ""}
  </form>`;
}
