import { api } from "../api.js";
import { $, formatDate, formatMoney, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";
import { rateText } from "./shared.js";

const PURPOSES = [["", "Choose…"], ["BUSINESS", "Business"], ["EDUCATION", "Education"], ["MEDICAL", "Medical"],
  ["HOME", "Home improvement"], ["AGRICULTURE", "Farming"], ["EMERGENCY", "Emergency"], ["PERSONAL", "Personal"], ["OTHER", "Other"]];
const EMPLOYMENT = [["", "Choose…"], ["EMPLOYED", "Employed"], ["SELF_EMPLOYED", "Self-employed"],
  ["UNEMPLOYED", "Unemployed"], ["STUDENT", "Student"], ["RETIRED", "Retired"]];
const FREQ = { WEEKLY: "Weekly", BIWEEKLY: "Every two weeks", MONTHLY: "Monthly" };
const PER = { WEEKLY: "a week", BIWEEKLY: "every two weeks", MONTHLY: "a month" };

const opts = (list, value) => list.map(([v, l]) => html`<option value="${v}" ${String(v) === String(value ?? "") ? "selected" : ""}>${l}</option>`);

export async function applyView(el, ctx) {
  mount(el, html`${pageHead("Apply for a loan")}${loadingBlock()}`);
  const [products, profileData, loans] = await Promise.all([
    api.get("loans/products/"), api.get("accounts/me/profile/"), api.get("loans/"),
  ]);
  if (!products.length) {
    mount(el, html`${pageHead("Apply for a loan")}<section class="panel"><p>No loan products are available right now.</p></section>`);
    return;
  }
  const wanted = ctx.query.get("loan");
  const draft = loans.find((l) => (wanted ? l.id === wanted : l.status === "DRAFT") && l.status === "DRAFT") || null;
  const inReview = loans.find((l) => ["SUBMITTED", "UNDER_REVIEW"].includes(l.status));
  const profile = profileData.profile || {};
  const productId = draft?.product.id ?? products[0].id;
  const product = () => products.find((p) => String(p.id) === String($("#apply-form", el).product.value)) || products[0];
  const start = {
    amount: draft?.amount ?? "", term_months: draft?.term_months ?? Math.min(6, products[0].max_term_months),
    repayment_frequency: draft?.repayment_frequency ?? "MONTHLY", purpose: draft?.purpose ?? "",
    purpose_details: draft?.purpose_details ?? "", employment_status: draft?.employment_status || profile.employment_status || "",
    monthly_income: draft?.monthly_income ?? profile.monthly_income ?? "", monthly_obligations: draft?.monthly_obligations ?? profile.monthly_obligations ?? "0",
    guarantor_email: draft?.guarantor?.email ?? "",
  };

  mount(el, html`
    ${pageHead(draft ? `Application ${draft.reference}` : "Apply for a loan",
      "Your rate comes from your trust score. Everything you'll pay is shown before you submit.")}
    ${inReview ? html`<p class="notice">Application <a href="#/loans/${inReview.id}">${inReview.reference}</a> is being reviewed. You can prepare a new one, but you can only submit it after that decision.</p>` : ""}
    <div class="apply">
      <form id="apply-form" class="panel form" novalidate>
        <h2>What you need</h2>
        ${products.length > 1 ? field("product", "Loan type", html`<select name="product">${opts(products.map((p) => [p.id, p.name]), productId)}</select>`)
          : html`<input type="hidden" name="product" value="${productId}"><p class="muted">${products[0].name}: ${products[0].description}</p>`}
        <div class="form__row">
          ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" required value="${start.amount}" placeholder="e.g. 20000">`, "")}
          ${field("term_months", "Repay over", html`<select name="term_months"></select>`)}
        </div>
        <div class="form__row">
          ${field("repayment_frequency", "Pay", html`<select name="repayment_frequency"></select>`)}
          ${field("purpose", "What it's for", html`<select name="purpose">${opts(PURPOSES, start.purpose)}</select>`)}
        </div>
        ${field("purpose_details", "Tell investors a bit more (optional)", html`<textarea name="purpose_details" rows="2" maxlength="1000">${start.purpose_details}</textarea>`,
          "Shown to investors without your name.")}
        <h2>Your finances</h2>
        <div class="form__row">
          ${field("employment_status", "Employment", html`<select name="employment_status">${opts(EMPLOYMENT, start.employment_status)}</select>`)}
          ${field("monthly_income", "Monthly income (KES)", html`<input name="monthly_income" inputmode="decimal" value="${start.monthly_income}">`)}
        </div>
        ${field("monthly_obligations", "Monthly commitments (KES)", html`<input name="monthly_obligations" inputmode="decimal" value="${start.monthly_obligations}">`,
          "Other loan repayments, rent and fixed costs. Changing income details here updates your profile; verified income will need checking again.")}
        <h2>Guarantor</h2>
        ${field("guarantor_email", "Guarantor's email", html`<input type="email" name="guarantor_email" value="${start.guarantor_email}" placeholder="Optional: they need a guarantor account">`,
          "With a guarantor you get the rate for your trust score; they must accept, and they hold your total interest in their wallet until you've paid it. Without one, your loan goes to the open-offers marketplace and investors offer their own rates.")}
        <div class="form__actions">
          <button class="btn btn--quiet" type="button" id="save-draft">Save draft</button>
          <button class="btn" type="submit" id="submit-app">Submit application</button>
          ${draft ? html`<a class="btn btn--quiet" href="#/loans/${draft.id}">View draft</a>` : ""}
        </div>
      </form>
      <aside class="panel quote" id="quote" aria-live="polite">
        <h2>Your quote</h2><p class="muted">Enter an amount to see what it would cost.</p>
      </aside>
    </div>`);

  const form = $("#apply-form", el);
  const quoteBox = $("#quote", el);
  const fillTermsAndFrequency = () => {
    const p = product();
    const term = form.term_months.value || start.term_months;
    form.term_months.innerHTML = "";
    for (let m = p.min_term_months; m <= p.max_term_months; m += 1) {
      const o = new Option(`${m} month${m === 1 ? "" : "s"}`, m, false, Number(term) === m);
      form.term_months.add(o);
    }
    const freq = form.repayment_frequency.value || start.repayment_frequency;
    form.repayment_frequency.innerHTML = "";
    p.frequencies.forEach((f) => form.repayment_frequency.add(new Option(FREQ[f], f, false, f === freq)));
    const amt = form.amount.closest(".field").querySelector(".field__help") || document.createElement("small");
    amt.className = "field__help";
    amt.textContent = `Between ${formatMoney(p.min_amount)} and ${formatMoney(p.max_amount)}.`;
    form.amount.closest(".field").appendChild(amt);
  };
  fillTermsAndFrequency();
  form.product?.addEventListener?.("change", () => { fillTermsAndFrequency(); requestQuote(); });

  const payload = () => {
    const d = Object.fromEntries(new FormData(form));
    d.amount = d.amount.replace(/[,\s]/g, "");
    d.monthly_income = d.monthly_income.replace(/[,\s]/g, "") || null;
    d.monthly_obligations = (d.monthly_obligations || "0").replace(/[,\s]/g, "") || "0";
    if (!d.employment_status) delete d.employment_status;
    if (!d.purpose) delete d.purpose;
    return d;
  };

  let timer = null;
  let seq = 0;
  async function requestQuote() {
    const d = payload();
    if (!/^\d+(\.\d{1,2})?$/.test(d.amount)) {
      mount(quoteBox, html`<h2>Your quote</h2><p class="muted">Enter an amount to see what it would cost.</p>`);
      return;
    }
    const mine = ++seq;
    try {
      const q = await api.post("loans/quote/", d);
      if (mine === seq) renderQuote(q, d);
    } catch (err) {
      if (mine === seq) mount(quoteBox, html`<h2>Your quote</h2><p class="notice notice--error">${err.fieldError?.("amount") || err.message}</p>`);
    }
  }
  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(requestQuote, 350); });
  form.addEventListener("change", () => { clearTimeout(timer); timer = setTimeout(requestQuote, 50); });

  function renderQuote(q, d) {
    const s = q.schedule;
    const blocking = q.problems.filter((p) => p.blocking);
    const notes = q.problems.filter((p) => !p.blocking);
    mount(quoteBox, html`
      <h2>Your quote</h2>
      ${s ? html`
        <p class="quote__big">${formatMoney(s.first_installment)} <span>${PER[s.frequency]}</span></p>
        <p class="muted">${s.installment_count} payments from ${formatDate(s.first_due_date)} to ${formatDate(s.final_due_date)}</p>
        <table class="kv">
          <tr><th scope="row">Interest rate</th><td>${rateText(q.annual_rate, q.rate_basis)} (${q.bracket?.label.toLowerCase()} bracket, trust score ${q.trust_score})${q.funding_mode === "OFFERS" ? html`<span class="sub">Without a guarantor, investors offer their own rates instead; this is a guide.</span>` : ""}</td></tr>
          <tr><th scope="row">Method</th><td>${s.method === "FLAT" ? "Flat" : "Reducing balance"}</td></tr>
          <tr><th scope="row">You borrow</th><td>${formatMoney(d.amount)}</td></tr>
          <tr><th scope="row">Total interest</th><td>${formatMoney(s.total_interest)}</td></tr>
          <tr><th scope="row">Total to repay</th><td><strong>${formatMoney(s.total_repayable)}</strong></td></tr>
          <tr><th scope="row">Fees</th><td>None</td></tr>
        </table>
        <details class="schedule"><summary>See every payment</summary>${scheduleTable(s.installments)}</details>`
      : q.trust_score === null
        ? html`<p>Your rate appears once your identity is verified and you have a trust score.</p>`
        : html`<p>Your bracket's rate is set by our credit team during review.</p>`}
      ${blocking.length ? html`<div class="problems"><p class="problems__title">Before you can submit</p>
        <ul>${blocking.map((p) => html`<li>${p.message}${linkFor(p.code)}</li>`)}</ul></div>` : ""}
      ${notes.length ? html`<ul class="ticks small">${notes.map((p) => html`<li>${p.message}</li>`)}</ul>` : ""}
      ${q.can_submit && s ? html`<p class="small ok-text">Ready to submit.</p>` : ""}
      <p class="small muted">The rate is confirmed when the loan is approved and then stays fixed for the life of the loan.</p>`);
  }

  async function save() {
    const d = payload();
    if (draft) return api.patch(`loans/${draft.id}/`, d);
    return api.post("loans/", d);
  }

  $("#save-draft", el).addEventListener("click", async (ev) => {
    clearFieldErrors(form);
    try {
      const loan = await busy(ev.currentTarget, "Saving…", save);
      toast("Draft saved", "ok");
      ctx.navigate("/apply", { loan: loan.id });
    } catch (err) {
      if (!showFieldErrors(form, err)) toast(err.message, "error");
    }
  });

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(form);
    const btn = $("#submit-app", el);
    try {
      const loan = await busy(btn, "Submitting…", async () => {
        const saved = await save();
        return api.post(`loans/${saved.id}/submit/`);
      });
      toast(`Application ${loan.reference} submitted`, "ok");
      ctx.navigate(`/loans/${loan.id}`);
    } catch (err) {
      if (!showFieldErrors(form, err)) toast(err.message, "error");
      requestQuote();
    }
  });

  requestQuote();
}

function linkFor(code) {
  const links = {
    kyc_required: ["#/kyc", "Verify identity"], email_unverified: ["#/profile", "Verify email"],
    phone_unverified: ["#/profile", "Verify phone"], income_missing: ["#/profile", "Add income"],
  };
  const l = links[code];
  return l ? html` <a href="${l[0]}">${l[1]}</a>` : "";
}

export function scheduleTable(rows, withStatus = false) {
  return html`<div class="table-wrap table-wrap--flat"><table class="table table--plain table--num">
    <thead><tr><th scope="col">#</th><th scope="col">Due</th><th scope="col">Principal</th><th scope="col">Interest</th><th scope="col">Payment</th><th scope="col">Left to repay</th>${withStatus ? html`<th scope="col">Status</th>` : ""}</tr></thead>
    <tbody>${rows.map((r) => html`<tr>
      <td>${r.sequence}</td><td class="nowrap">${formatDate(r.due_date)}</td>
      <td>${formatMoney(r.principal)}</td><td>${formatMoney(r.interest)}</td>
      <td><strong>${formatMoney(r.total)}</strong></td><td>${formatMoney(r.balance_after)}</td>
      ${withStatus ? html`<td>${(r.status || "").replace(/_/g, " ").toLowerCase()}</td>` : ""}
    </tr>`)}</tbody></table></div>`;
}
