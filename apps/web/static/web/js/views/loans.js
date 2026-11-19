import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDate, formatDateTime, formatMoney, html, mount, toast } from "../ui.js";
import { busy, emptyState, field, loadingBlock, loanTag, pageHead, showFieldErrors } from "./common.js";
import { scheduleTable } from "./apply.js";
import { documentLinks, wireDocuments } from "./documents.js";
import { idemKey, money, rateText, statusTag } from "./shared.js";

const PER = { WEEKLY: "weekly", BIWEEKLY: "every two weeks", MONTHLY: "monthly" };

export async function myLoansView(el) {
  mount(el, html`${pageHead("My loans")}${loadingBlock()}`);
  const loans = await api.get("loans/");
  mount(el, html`
    ${pageHead("My loans", "Every application and loan, from draft to the final payment.")}
    ${can("loans.apply") ? html`<p><a class="btn" href="#/apply">Apply for a loan</a></p>` : ""}
    ${loans.length ? html`<div class="table-wrap"><table class="table">
      <thead><tr><th scope="col">Loan</th><th scope="col">Amount</th><th scope="col">Rate</th><th scope="col">Repayments</th><th scope="col">Status</th><th scope="col">Started</th></tr></thead>
      <tbody>${loans.map((l) => html`<tr>
        <td><a class="linkish" href="#/loans/${l.id}">${l.reference}</a><span class="sub">${l.purpose_label}</span></td>
        <td class="nowrap">${formatMoney(l.amount)}</td>
        <td>${l.annual_rate ? rateText(l.annual_rate, l.rate_basis) : html`<span class="muted">${l.funding_mode === "OFFERS" ? "Set by offers" : "Not set"}</span>`}</td>
        <td>${l.installment_amount ? html`${formatMoney(l.installment_amount)} <span class="sub">${PER[l.repayment_frequency]}, ${l.installment_count} payments</span>` : html`<span class="muted">After pricing</span>`}</td>
        <td>${loanTag(l.status, l.status_label)}</td>
        <td class="nowrap">${formatDate(l.created_at)}</td>
      </tr>`)}</tbody></table></div>`
    : html`<section class="panel">${emptyState("No loans yet", "Applications you start will appear here, with their status and repayment schedule.")}</section>`}`);
}

const PRE_PAYOUT = ["APPROVED", "PUBLISHED", "PARTIALLY_FUNDED", "FULLY_FUNDED", "GUARANTOR_PENDING", "READY_FOR_DISBURSEMENT"];
const REPAYING = ["ACTIVE", "OVERDUE", "DEFAULTED"];

export async function loanDetailView(el, ctx) {
  mount(el, html`${pageHead("Loan")}${loadingBlock()}`);
  const l = await api.get(`loans/${ctx.params.id}/`);
  const [wallet, repayments] = await Promise.all([
    REPAYING.includes(l.status) && can("wallet.view_own") ? api.get("wallet/") : null,
    REPAYING.includes(l.status) || l.status === "COMPLETED" ? api.get("repayments/", { loan: l.id }) : null,
  ]);
  const early = ["DRAFT", "SUBMITTED", "UNDER_REVIEW"].includes(l.status);
  const cancellable = early || PRE_PAYOUT.includes(l.status);
  const docsOpen = early && can("loans.apply");
  const g = l.guarantor;
  const needsGuarantor = l.funding_mode === "STANDARD" && PRE_PAYOUT.includes(l.status) && g && ["DECLINED", "WITHDRAWN"].includes(g.status);
  const pendingExt = l.extensions.find((e) => ["REQUESTED", "AWAITING_CONSENT"].includes(e.status));

  mount(el, html`
    <a class="back" href="#/loans">All loans</a>
    <header class="page-head page-head--row">
      <div><h1>${l.reference}</h1><p class="lead">${formatMoney(l.amount)} for ${l.purpose_label.toLowerCase()}, over ${l.term_months} month${l.term_months === 1 ? "" : "s"} · ${l.funding_mode_label}</p></div>
      ${loanTag(l.status, l.status_label)}
    </header>
    ${l.status === "DRAFT" ? html`<p class="notice">This application hasn't been submitted. <a href="#/apply?loan=${l.id}">Continue the application</a></p>` : ""}
    ${l.status === "REJECTED" ? html`<div class="notice notice--error"><p><strong>Not approved.</strong> ${l.decision_reason}</p></div>` : ""}
    ${statusNotice(l)}

    ${["PUBLISHED", "PARTIALLY_FUNDED"].includes(l.status) ? fundingPanel(l) : ""}
    ${needsGuarantor ? html`<section class="panel panel--feature"><h2>Nominate another guarantor</h2>
      <p class="panel__text">${g.name} ${g.status === "DECLINED" ? "declined" : "withdrew"}${g.note ? `: "${g.note}"` : ""}. Your loan can't be paid out without a guarantor who accepts. They'll need your total interest (${money(l.total_interest)}) in their wallet; it's locked until you've paid the interest.</p>
      <form class="form form--inline" id="guarantor-form" novalidate>${field("guarantor_email", "Guarantor's email", html`<input name="guarantor_email" type="email">`)}
      <button class="btn" type="submit">Send request</button></form></section>` : ""}
    ${l.agreement && !l.agreement.accepted_at && l.status === "READY_FOR_DISBURSEMENT" ? agreementPanel(l) : ""}
    ${REPAYING.includes(l.status) ? payPanel(l, wallet) : ""}

    <div class="columns">
      <section class="panel">
        <h2>Terms</h2>
        <table class="kv">
          <tr><th scope="row">Amount</th><td>${formatMoney(l.amount)}</td></tr>
          <tr><th scope="row">Interest rate</th><td>${l.annual_rate ? rateText(l.annual_rate, l.rate_basis) : l.funding_mode === "OFFERS" ? "Set by the offers you accept" : "Set at review"}${l.bracket_label && l.funding_mode === "STANDARD" ? `, ${l.bracket_label.toLowerCase()} bracket` : ""}</td></tr>
          <tr><th scope="row">Method</th><td>${l.interest_method_label || l.product.interest_method_label}</td></tr>
          <tr><th scope="row">Repayments</th><td>${l.installment_amount ? `${formatMoney(l.installment_amount)} ${PER[l.repayment_frequency]}, ${l.installment_count} payments` : l.frequency_label}</td></tr>
          <tr><th scope="row">Total interest</th><td>${money(l.total_interest)}</td></tr>
          <tr><th scope="row">Total to repay</th><td>${l.total_repayable ? html`<strong>${formatMoney(l.total_repayable)}</strong>` : "–"}</td></tr>
          <tr><th scope="row">Trust score used</th><td>${l.trust_score_snapshot ?? "–"}</td></tr>
          <tr><th scope="row">Guarantor</th><td>${g ? html`${g.name} ${statusTag(g.status, g.status_label)}${Number(g.locked_interest) > 0 ? html`<span class="sub">${money(g.locked_interest)} interest locked in their wallet</span>` : ""}` : "None (open offers)"}</td></tr>
          ${l.extension_count ? html`<tr><th scope="row">Extensions</th><td>${l.extension_count}</td></tr>` : ""}
        </table>
        ${l.terms_locked ? html`<p class="small muted">Terms locked on ${formatDate(l.terms_locked_at)}. Your rate stays the same even if your trust score changes.</p>` : ""}
        ${l.agreement?.accepted_at ? html`<details class="history"><summary>Loan agreement (version ${l.agreement.version}, accepted ${formatDate(l.agreement.accepted_at)})</summary><pre class="code-out">${l.agreement.text}</pre></details>` : ""}
        ${l.agreement && !l.agreement.accepted_at && REPAYING.includes(l.status) ? html`<p class="notice notice--warn">Your terms changed (version ${l.agreement.version}). <button class="btn btn--small" type="button" id="accept-new-agreement">Review and accept</button></p>` : ""}
        ${cancellable ? html`<form id="cancel-form" class="form form--inline" novalidate>
          ${field("reason", early ? "Cancel this application" : "Cancel this loan (investors are refunded)", html`<input name="reason" placeholder="Reason (optional)">`)}
          <button class="btn btn--quiet btn--danger-text" type="submit">Cancel</button></form>` : ""}
      </section>
      <section class="panel">
        <h2>Progress</h2>
        <ol class="timeline">${l.history.map((h) => html`<li><p class="timeline__what">${h.to_label}</p>
          <p class="timeline__when">${formatDateTime(h.at)}</p>${h.reason ? html`<p class="timeline__why">${h.reason}</p>` : ""}</li>`)}</ol>
        <h3>Documents</h3>
        <p>${documentLinks(l.documents)}</p>
        ${docsOpen ? html`<form id="doc-form" class="form" novalidate>
          <div class="form__row">
            ${field("description", "What is it?", html`<input name="description" maxlength="120" placeholder="e.g. 3-month M-Pesa statement">`)}
            ${field("file", "File", html`<input type="file" name="file" accept="image/jpeg,image/png,application/pdf">`, "JPG, PNG or PDF, up to 5 MB.")}
          </div>
          <button class="btn btn--quiet" type="submit">Add document</button></form>` : ""}
      </section>
    </div>

    ${REPAYING.includes(l.status) && can("extensions.request") ? extensionPanel(l, pendingExt) : ""}
    ${l.extensions.length ? html`<section class="panel"><h2>Extension requests</h2><table class="table table--plain">
      <thead><tr><th scope="col">Asked</th><th scope="col">Days</th><th scope="col">Cost</th><th scope="col">Status</th><th scope="col">Outcome</th><th></th></tr></thead>
      <tbody>${l.extensions.map((e) => html`<tr><td class="nowrap">${formatDate(e.created_at)}</td><td>${e.days}</td>
        <td class="nowrap">${money((Number(e.extension_interest) + Number(e.extension_fee)).toFixed(2))}</td>
        <td>${statusTag(e.status, e.status_label)}${e.consent_deadline && e.status === "AWAITING_CONSENT" ? html`<span class="sub">Investors answer by ${formatDate(e.consent_deadline)}</span>` : ""}</td>
        <td class="small">${e.decision_reason}</td>
        <td>${["REQUESTED", "AWAITING_CONSENT"].includes(e.status) ? html`<button class="btn btn--quiet btn--small" data-cancel-ext="${e.id}">Withdraw</button>` : ""}</td></tr>`)}</tbody></table></section>` : ""}

    <section class="panel">
      <h2>${l.terms_locked ? "Repayment schedule" : "Estimated repayment schedule"}</h2>
      ${l.schedule.length ? (l.disbursed_at ? liveSchedule(l.schedule) : scheduleTable(l.schedule, l.terms_locked)) : html`<p class="muted">${l.funding_mode === "OFFERS" ? "The schedule is set from the rates of the offers you accept." : "The schedule appears once the rate is set."}</p>`}
      ${l.terms_locked && !l.disbursed_at && l.schedule.length ? html`<p class="small muted">Due dates are re-set from the day the money is paid out.</p>` : ""}
    </section>
    ${repayments?.results.length ? html`<section class="panel"><h2>Payments made</h2><table class="table table--plain">
      <thead><tr><th scope="col">When</th><th scope="col" class="num">Paid</th><th scope="col" class="num">Principal</th><th scope="col" class="num">Interest</th><th scope="col" class="num">Fees</th></tr></thead>
      <tbody>${repayments.results.map((r) => html`<tr><td class="nowrap">${formatDateTime(r.created_at)}</td><td class="num">${money(r.amount)}</td>
        <td class="num">${money(r.principal)}</td><td class="num">${money((Number(r.interest) + Number(r.extension_interest)).toFixed(2))}</td>
        <td class="num">${money((Number(r.late_fee) + Number(r.extension_fee)).toFixed(2))}</td></tr>`)}</tbody></table></section>` : ""}`);

  wireDetail(el, l, ctx);
}

function statusNotice(l) {
  const n = {
    APPROVED: html`<p class="notice notice--success">Approved. It opens to investors shortly.</p>`,
    PUBLISHED: html`<p class="notice notice--success">Open to investors until ${formatDateTime(l.funding_expires_at)}.</p>`,
    PARTIALLY_FUNDED: html`<p class="notice notice--success">Investors are funding your loan. Open until ${formatDateTime(l.funding_expires_at)}.</p>`,
    GUARANTOR_PENDING: html`<p class="notice notice--warn">Fully funded. Waiting for your guarantor to accept.</p>`,
    READY_FOR_DISBURSEMENT: l.agreement?.accepted_at ? html`<p class="notice notice--success">Agreement accepted. Our team will pay the money into your wallet shortly.</p>` : "",
    OVERDUE: html`<p class="notice notice--error">A payment is overdue${l.overdue_since ? ` since ${formatDate(l.overdue_since)}` : ""}. Pay now to stop more late fees and protect your trust score.</p>`,
    DEFAULTED: html`<p class="notice notice--error">This loan is in default. Paying what you owe still counts, and stops further action. Contact support to agree a plan.</p>`,
    COMPLETED: html`<p class="notice notice--success">Repaid in full on ${formatDate(l.completed_at)}. Thank you.</p>`,
  };
  return n[l.status] || "";
}

function fundingPanel(l) {
  const f = l.funding;
  const open = l.offers.filter((o) => o.status === "OPEN");
  return html`<section class="panel">
    <h2>Funding</h2>
    <progress max="100" value="${f.percent}">${f.percent}%</progress>
    <p>${money(f.funded)} of ${formatMoney(l.amount)} (${f.percent}%) from ${f.investors} investor${f.investors === 1 ? "" : "s"}. ${money(f.remaining)} to go.</p>
    ${l.funding_mode === "OFFERS" ? html`
      <h3>Offers</h3>
      <p class="small muted">Investors set their own rate because your loan has no guarantor. Accept offers until the loan is full; your rate becomes the average of the accepted offers, weighted by amount. You can chat with an investor before deciding.</p>
      ${open.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Investor</th><th scope="col" class="num">Amount</th><th scope="col" class="num">Rate</th><th scope="col">Message</th><th></th></tr></thead>
        <tbody>${open.map((o) => html`<tr><td>${o.investor}</td><td class="num nowrap">${money(o.amount)}</td><td class="num">${rateText(o.rate, l.rate_basis)}</td>
          <td class="small">${o.message}</td>
          <td class="nowrap"><button class="btn btn--small" data-accept="${o.id}" ${Number(o.amount) > Number(f.remaining) ? "disabled" : ""}>Accept</button>
            <button class="btn btn--quiet btn--small" data-decline="${o.id}">Decline</button>
            <button class="btn btn--quiet btn--small" data-chat="${o.investor_id}">Chat</button></td></tr>`)}</tbody></table>`
        : html`<p class="muted">No offers yet. Investors see your trust score and risk rating; repaying on time raises your score.</p>`}
      ${l.offers.filter((o) => o.status !== "OPEN").length ? html`<details class="history"><summary>Earlier offers</summary><ul>${l.offers.filter((o) => o.status !== "OPEN").map((o) => html`<li>${o.investor}: ${money(o.amount)} at ${o.rate}% — ${o.status_label}</li>`)}</ul></details>` : ""}` : ""}
  </section>`;
}

function agreementPanel(l) {
  return html`<section class="panel panel--feature">
    <h2>Your loan agreement</h2>
    <p class="panel__text">Read the agreement. The money is paid into your wallet once you accept.</p>
    <pre class="code-out">${l.agreement.text}</pre>
    <label class="check"><input type="checkbox" id="agree-box"> I've read and accept these terms and the repayment schedule.</label>
    <button class="btn" type="button" id="accept-agreement" disabled>Accept agreement</button>
  </section>`;
}

function payPanel(l, wallet) {
  const o = l.outstanding;
  return html`<section class="panel panel--feature">
    <h2>Pay</h2>
    <div class="stats">
      <div class="stat"><p class="stat__label">Next payment</p><p class="stat__value">${money(o.next_due_amount)}</p><p class="stat__note">${o.next_due_date ? `Due ${formatDate(o.next_due_date)}` : ""}</p></div>
      <div class="stat"><p class="stat__label">Everything still owed</p><p class="stat__value">${money(o.total)}</p>
        <p class="stat__note">${Number(o.late_fee) > 0 ? `Includes ${money(o.late_fee)} late fees. ` : ""}${Number(o.extension_interest) + Number(o.extension_fee) > 0 ? "Includes extension charges." : ""}</p></div>
      ${wallet ? html`<div class="stat"><p class="stat__label">In your wallet</p><p class="stat__value">${money(wallet.balances.available)}</p></div>` : ""}
    </div>
    <form class="form" id="pay-form" novalidate>
      <div class="form__row">
        ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" value="${o.next_due_amount}">`, "Paying early or more than is due raises your trust score; extra goes to the next installments.")}
        ${field("source", "Pay from", html`<select name="source"><option value="wallet">My wallet balance</option>${(wallet?.providers || []).map((p) => html`<option value="${p.code}">${p.label} (deposit and pay)</option>`)}</select>`)}
      </div>
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Pay now</button>
    </form>
  </section>`;
}

function extensionPanel(l, pending) {
  if (pending) return "";
  return html`<section class="panel"><h2>Need more time?</h2>
    <p class="panel__text">Ask to move all your remaining payments later. You'll see the exact cost first. Investors may be asked to agree, and an extension affects your trust score less if you ask before a payment is missed.</p>
    <form class="form" id="ext-form" novalidate>
      <div class="form__row">
        ${field("days", "How many days?", html`<input name="days" inputmode="numeric" value="30">`)}
        ${field("reason", "Why do you need it?", html`<input name="reason" maxlength="1000">`)}
      </div>
      <p class="small" id="ext-quote"></p><p class="form__error" data-error></p>
      <button class="btn btn--quiet" type="button" id="ext-check">See the cost</button>
      <button class="btn" type="submit" id="ext-submit" disabled>Request extension</button>
    </form></section>`;
}

function liveSchedule(rows) {
  return html`<div class="table-wrap table-wrap--flat"><table class="table table--plain table--num">
    <thead><tr><th scope="col">#</th><th scope="col">Due</th><th scope="col">Principal</th><th scope="col">Interest</th><th scope="col">Fees & extension</th><th scope="col">Due in total</th><th scope="col">Paid</th><th scope="col">Status</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr>
      <td>${r.sequence}</td><td class="nowrap">${formatDate(r.due_date)}${r.original_due_date && r.original_due_date !== r.due_date ? html`<span class="sub">was ${formatDate(r.original_due_date)}</span>` : ""}</td>
      <td>${money(r.principal)}</td><td>${money(r.interest)}</td>
      <td>${money((Number(r.late_fee) + Number(r.extension_fee) + Number(r.extension_interest)).toFixed(2))}</td>
      <td><strong>${money(r.total)}</strong></td><td>${money(r.paid)}</td><td>${statusTag(r.status, r.status_label)}</td></tr>`)}</tbody></table></div>`;
}

function wireDetail(el, l, ctx) {
  wireDocuments(el);
  const run = async (btn, label, fn, ok) => {
    try { await busy(btn, label, fn); if (ok) toast(ok, "ok"); ctx.rerender(); } catch (err) { toast(err.message, "error"); }
  };
  $("#cancel-form", el)?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    if (!window.confirm("Cancel this loan? Any investors get their money back. This can't be undone.")) return;
    run(form.querySelector("button"), "Cancelling…", () => api.post(`loans/${l.id}/cancel/`, { reason: form.reason.value }), "Loan cancelled");
  });
  $("#doc-form", el)?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    if (!form.file.files.length) { form.querySelector("[data-for=file]").textContent = "Choose a file."; return; }
    try {
      await busy(form.querySelector("button"), "Uploading…", () => api.upload(`loans/${l.id}/documents/`, new FormData(form)));
      toast("Document added", "ok");
      ctx.rerender();
    } catch (err) { if (!showFieldErrors(form, err)) toast(err.message, "error"); }
  });
  $("#guarantor-form", el)?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    run(form.querySelector("button"), "Sending…", () => api.post(`loans/${l.id}/guarantor/`, { guarantor_email: form.guarantor_email.value.trim() }), "Request sent to your new guarantor");
  });
  const box = $("#agree-box", el);
  box?.addEventListener("change", () => { $("#accept-agreement", el).disabled = !box.checked; });
  $("#accept-agreement", el)?.addEventListener("click", (ev) => run(ev.currentTarget, "Accepting…", () => api.post(`loans/${l.id}/agreement/`), "Agreement accepted"));
  $("#accept-new-agreement", el)?.addEventListener("click", (ev) => {
    if (window.confirm(`${l.agreement.text}\n\nAccept these updated terms?`)) run(ev.currentTarget, "…", () => api.post(`loans/${l.id}/agreement/`), "Updated agreement accepted");
  });
  $$("[data-accept]", el).forEach((b) => b.addEventListener("click", () => {
    const o = l.offers.find((x) => String(x.id) === b.dataset.accept);
    if (window.confirm(`Accept ${o.investor}'s offer of ${money(o.amount)} at ${o.rate}%?`)) run(b, "…", () => api.post(`loans/${l.id}/offers/${o.id}/`, { accept: true }), "Offer accepted");
  }));
  $$("[data-decline]", el).forEach((b) => b.addEventListener("click", () => {
    const reason = window.prompt("Decline this offer. Optional note for the investor:", "") ?? null;
    if (reason !== null) run(b, "…", () => api.post(`loans/${l.id}/offers/${b.dataset.decline}/`, { accept: false, reason }), "Offer declined");
  }));
  $$("[data-chat]", el).forEach((b) => b.addEventListener("click", async () => {
    try { const c = await api.post("chat/", { loan_id: l.id, user_id: b.dataset.chat }); ctx.navigate(`/chat/${c.id}`); }
    catch (err) { toast(err.message, "error"); }
  }));
  $$("[data-cancel-ext]", el).forEach((b) => b.addEventListener("click", () => run(b, "…", () => api.post(`loans/${l.id}/extension/${b.dataset.cancelExt}/cancel/`), "Request withdrawn")));

  const pay = $("#pay-form", el);
  pay?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = pay.querySelector("[data-error]");
    err.textContent = "";
    const amount = pay.amount.value.trim();
    try {
      if (pay.source.value === "wallet") {
        await busy(pay.querySelector("button"), "Paying…", () => api.post(`loans/${l.id}/repay/`, { amount, idempotency_key: idemKey() }));
        toast("Payment applied", "ok");
      } else {
        await busy(pay.querySelector("button"), "Starting…", () => api.post("wallet/deposit/", { amount, provider: pay.source.value, loan_id: l.id, idempotency_key: idemKey() }));
        toast(pay.source.value === "SANDBOX" ? "Deposit started: confirm it on the Wallet page and it's applied to this loan." : "Check your phone and enter your M-Pesa PIN. The payment is applied when M-Pesa confirms it.", "ok");
      }
      ctx.rerender();
    } catch (e) { if (!showFieldErrors(pay, e)) err.textContent = e.message; }
  });

  const ext = $("#ext-form", el);
  if (ext) {
    const out = $("#ext-quote", el);
    $("#ext-check", el).addEventListener("click", async () => {
      try {
        const q = await api.get(`loans/${l.id}/extension/`, { days: ext.days.value.trim() });
        const total = (Number(q.extension_interest) + Number(q.extension_fee)).toFixed(2);
        out.textContent = q.problems.length ? q.problems[0]
          : `Extra interest ${money(q.extension_interest)} + fee ${money(q.extension_fee)} = ${money(total)}, added to your next payment. ${q.investor_consent === "NONE" ? "" : `Investors get ${q.consent_days} days to respond.`}`;
        out.className = q.problems.length ? "small bad-text" : "small";
        $("#ext-submit", el).disabled = Boolean(q.problems.length);
      } catch (e) { out.textContent = e.message; }
    });
    ext.days.addEventListener("input", () => { $("#ext-submit", el).disabled = true; out.textContent = ""; });
    ext.addEventListener("submit", (ev) => {
      ev.preventDefault();
      run($("#ext-submit", el), "Sending…", () => api.post(`loans/${l.id}/extension/`, { days: ext.days.value.trim(), reason: ext.reason.value.trim() }), "Extension requested");
    });
  }
}
