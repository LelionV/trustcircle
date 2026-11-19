import { api } from "../api.js";
import { $, $$, formatDateTime, formatMoney, html, mount, raw, toast } from "../ui.js";
import { busy, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";

const SECTIONS = [["brackets", "Interest brackets"], ["platform", "Fees, limits & offers"], ["trust", "Trust scoring"],
  ["risk", "Risk rating"], ["products", "Loan products"], ["jobs", "Scheduled jobs"]];
export const BASIS = { MONTHLY: "% per month", ANNUAL: "% per year", PER_LOAN: "% of the loan, once" };
const BAND_LABELS = {
  early_7_plus: "7+ days early", early_3_6: "3–6 days early", early_1_2: "1–2 days early", on_time: "On the due date",
  late_1_3: "1–3 days late", late_4_7: "4–7 days late", late_8_14: "8–14 days late", late_15_plus: "15+ days late",
};
const FREQ = { WEEKLY: "Weekly", BIWEEKLY: "Every two weeks", MONTHLY: "Monthly" };

// attrs is always a literal written in this file, never user data.
const num = (name, value, attrs = "") => html`<input name="${name}" value="${value}" inputmode="decimal" ${raw(attrs)} class="input--num">`;

function history(rows) {
  return html`<details class="history"><summary>Version history</summary><table class="table table--plain">
    <thead><tr><th scope="col">Version</th><th scope="col">Changed</th><th scope="col">By</th><th scope="col">Reason</th></tr></thead>
    <tbody>${rows.map((h) => html`<tr><td>${h.version}${h.is_active ? html` <span class="tag tag--ok">Active</span>` : ""}</td>
      <td class="nowrap">${formatDateTime(h.at)}</td><td>${h.by}</td><td class="small">${h.reason}</td></tr>`)}</tbody></table></details>`;
}

const reasonField = () => field("reason", "Why are you changing this?", html`<input name="reason" maxlength="1000" placeholder="Kept with this version in the audit trail">`);

export async function adminConfigView(el, ctx) {
  const tab = ctx.query.get("tab") || "brackets";
  mount(el, html`${pageHead("Configuration")}${loadingBlock()}`);
  const [cfg, products] = await Promise.all([
    api.get("admin/config/"),
    tab === "products" ? api.get("admin/products/") : tab === "platform" ? api.get("admin/config/platform/") : null]);

  mount(el, html`
    ${pageHead("Configuration", "The rules the platform runs on. Each save creates a new version; loans already approved keep the terms they were given.")}
    <nav class="tabs" aria-label="Settings">${SECTIONS.map(([k, l]) => html`<a class="tabs__tab" href="#/admin/config?tab=${k}" ${k === tab ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    <div id="config-body"></div>`);
  const body = $("#config-body", el);
  ({ brackets: bracketsTab, trust: trustTab, risk: riskTab, products: productsTab, platform: platformTab, jobs: jobsTab })[tab](body, cfg, products, ctx);
}

// --- Interest brackets -----------------------------------------------------------

function bracketRow(r = { min_score: "", max_score: "", label: "", annual_rate: "" }) {
  return html`<tr>
    <td>${num("min_score", r.min_score, 'aria-label="Lowest score"')}</td>
    <td>${num("max_score", r.max_score, 'aria-label="Highest score"')}</td>
    <td><input name="label" value="${r.label}" maxlength="40" aria-label="Name"></td>
    <td>${num("annual_rate", r.annual_rate ?? "", 'aria-label="Rate" placeholder="Manual"')}</td>
    <td><button class="btn btn--quiet btn--small" type="button" data-remove>Remove</button></td>
  </tr>`;
}

function bracketsTab(host, cfg, _p, ctx) {
  mount(host, html`<section class="panel">
    <h2>Interest brackets (version ${cfg.brackets.version})</h2>
    <p class="panel__text">Rates by trust score. Brackets must cover 0–100 with no gaps. Leave the rate empty for brackets that need a manually set rate. The rate type below decides how every rate in the table is read; loans already approved keep theirs.</p>
    <form id="brackets-form" class="form" novalidate>
      ${field("rate_basis", "Interest is charged", html`<select name="rate_basis">${Object.entries(BASIS).map(([k, l]) => html`<option value="${k}" ${k === cfg.brackets.rate_basis ? "selected" : ""}>${l}</option>`)}</select>`,
        "Monthly is the default. Changing it reinterprets the numbers in the table, so review them before saving.")}
      <div class="table-wrap table-wrap--flat"><table class="table table--plain table--edit">
        <thead><tr><th scope="col">From score</th><th scope="col">To score</th><th scope="col">Name</th><th scope="col">Rate (<span id="basis-label">${BASIS[cfg.brackets.rate_basis]}</span>)</th><th></th></tr></thead>
        <tbody>${cfg.brackets.rows.map((r) => bracketRow(r))}</tbody>
      </table></div>
      <p><button class="btn btn--quiet btn--small" type="button" id="add-bracket">Add a bracket</button></p>
      ${reasonField()}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save as version ${cfg.brackets.version + 1}</button>
    </form>
    ${history(cfg.brackets.history)}
  </section>`);
  const form = $("#brackets-form", host);
  const tbody = form.querySelector("tbody");
  form.rate_basis.addEventListener("change", () => { $("#basis-label", host).textContent = BASIS[form.rate_basis.value]; });
  const wireRemove = () => $$("[data-remove]", form).forEach((b) => { b.onclick = () => b.closest("tr").remove(); });
  wireRemove();
  $("#add-bracket", host).addEventListener("click", () => {
    tbody.insertAdjacentHTML("beforeend", String(bracketRow()));
    wireRemove();
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const brackets = $$("tbody tr", form).map((tr) => ({
      min_score: tr.querySelector("[name=min_score]").value, max_score: tr.querySelector("[name=max_score]").value,
      label: tr.querySelector("[name=label]").value, annual_rate: tr.querySelector("[name=annual_rate]").value || null,
    }));
    await save(form, "admin/config/brackets/", { brackets, rate_basis: form.rate_basis.value, reason: form.reason.value.trim() }, "Interest brackets saved", ctx);
  });
}

// --- Trust ------------------------------------------------------------------------------

function trustTab(host, cfg, _p, ctx) {
  const p = cfg.trust.parameters;
  const labels = cfg.trust.component_labels;
  mount(host, html`<section class="panel">
    <h2>Trust scoring (version ${cfg.trust.version})</h2>
    <p class="panel__text">Saving rescores every borrower straight away. Approved loans keep their locked rate.</p>
    <form id="trust-form" class="form" novalidate>
      <h3>Weights (must add up to 100)</h3>
      <div class="grid-fields">${Object.entries(p.weights).map(([k, v]) => field(`w_${k}`, labels[k] || k, num(`w_${k}`, v)))}</div>
      <p class="small" id="weight-total"></p>
      <h3>Points for each scheduled installment</h3>
      <div class="grid-fields">${Object.entries(BAND_LABELS).map(([k, l]) => field(`pp_${k}`, l, num(`pp_${k}`, p.punctuality_points[k])))}</div>
      <h3>Limits and penalties</h3>
      <div class="grid-fields">
        ${field("initial_score", "Starting score for new borrowers", num("initial_score", p.initial_score))}
        ${field("full_confidence_installments", "Installments until history fully counts", num("full_confidence_installments", p.full_confidence_installments))}
        ${field("reward_cap_per_loan", "Most bonus points from one loan", num("reward_cap_per_loan", p.reward_cap_per_loan))}
        ${field("min_installment_amount", "Smallest installment that counts (KES)", num("min_installment_amount", p.min_installment_amount))}
        ${field("default_penalty", "Points lost per default", num("default_penalty", p.default_penalty))}
        ${field("manual_adjustment_limit", "Largest manual adjustment", num("manual_adjustment_limit", p.manual_adjustment_limit))}
        ${field("ext_before_due", "Extension asked before the due date", num("ext_before_due", p.extension_penalties.before_due))}
        ${field("ext_after_missed", "Extension after a missed payment", num("ext_after_missed", p.extension_penalties.after_missed))}
        ${field("ext_repeat_extra", "Extra for each repeat extension", num("ext_repeat_extra", p.extension_penalties.repeat_extra))}
        ${field("early_days", "Whole loan repaid at least this many days early…", num("early_days", (p.early_completion_bonus || {}).min_days_early ?? 7))}
        ${field("early_points", "…earns this many bonus points", num("early_points", (p.early_completion_bonus || {}).points ?? 3))}
      </div>
      ${reasonField()}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save as version ${cfg.trust.version + 1}</button>
    </form>
    ${history(cfg.trust.history)}
  </section>`);
  const form = $("#trust-form", host);
  const total = () => {
    const sum = Object.keys(p.weights).reduce((s, k) => s + (Number(form[`w_${k}`].value) || 0), 0);
    const out = $("#weight-total", host);
    out.textContent = `Total: ${sum}`;
    out.className = sum === 100 ? "small ok-text" : "small bad-text";
  };
  form.addEventListener("input", total);
  total();
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = (n) => form[n].value.trim();
    const parameters = {
      initial_score: v("initial_score"),
      weights: Object.fromEntries(Object.keys(p.weights).map((k) => [k, v(`w_${k}`)])),
      punctuality_points: Object.fromEntries(Object.keys(BAND_LABELS).map((k) => [k, v(`pp_${k}`)])),
      default_penalty: v("default_penalty"), reward_cap_per_loan: v("reward_cap_per_loan"),
      min_installment_amount: v("min_installment_amount"), full_confidence_installments: v("full_confidence_installments"),
      manual_adjustment_limit: v("manual_adjustment_limit"),
      extension_penalties: { before_due: v("ext_before_due"), after_missed: v("ext_after_missed"), repeat_extra: v("ext_repeat_extra") },
      early_completion_bonus: { min_days_early: v("early_days"), points: v("early_points") },
    };
    await save(form, "admin/config/trust/", { parameters, reason: v("reason") }, "Trust rules saved; borrowers rescored", ctx, "put");
  });
}

// --- Risk -----------------------------------------------------------------------------------

function riskTab(host, cfg, _p, ctx) {
  const p = cfg.risk.parameters;
  mount(host, html`<section class="panel">
    <h2>Risk rating (version ${cfg.risk.version})</h2>
    <p class="panel__text">Higher risk scores mean more lending risk. Saving reassesses every borrower and guarantor.</p>
    <form id="risk-form" class="form" novalidate>
      <h3>Factor weights (must add up to 100)</h3>
      <div class="grid-fields">${Object.entries(p.weights).map(([k, w]) => field(`w_${k}`, cfg.risk.factor_labels[k] || k, num(`w_${k}`, w)))}</div>
      <h3>Classification by score</h3>
      <div class="table-wrap table-wrap--flat"><table class="table table--plain table--edit">
        <thead><tr><th scope="col">Rating</th><th scope="col">From</th><th scope="col">To</th></tr></thead>
        <tbody>${p.thresholds.map((t, i) => html`<tr><td>${cfg.risk.class_labels[t.class]}</td>
          <td>${num(`t_min_${i}`, t.min)}</td><td>${num(`t_max_${i}`, t.max)}</td></tr>`)}</tbody></table></div>
      ${reasonField()}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save as version ${cfg.risk.version + 1}</button>
    </form>
    ${history(cfg.risk.history)}
  </section>`);
  const form = $("#risk-form", host);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const parameters = {
      weights: Object.fromEntries(Object.keys(p.weights).map((k) => [k, form[`w_${k}`].value.trim()])),
      thresholds: p.thresholds.map((t, i) => ({ class: t.class, min: form[`t_min_${i}`].value.trim(), max: form[`t_max_${i}`].value.trim() })),
    };
    await save(form, "admin/config/risk/", { parameters, reason: form.reason.value.trim() }, "Risk rules saved; ratings reassessed", ctx, "put");
  });
}

// --- Products ---------------------------------------------------------------------------------

function productForm(pr) {
  const id = pr?.id ?? "new";
  return html`<form class="form product-form" data-product="${id}" novalidate>
    <div class="form__row">
      ${field("name", "Name", html`<input name="name" value="${pr?.name ?? ""}" maxlength="80">`)}
      ${field("is_active", "Available to borrowers", html`<select name="is_active"><option value="true" ${pr?.is_active !== false ? "selected" : ""}>Yes</option><option value="false" ${pr?.is_active === false ? "selected" : ""}>No</option></select>`)}
    </div>
    ${field("description", "Description", html`<input name="description" value="${pr?.description ?? ""}">`)}
    <div class="grid-fields">
      ${field("min_amount", "Smallest amount (KES)", num("min_amount", pr?.min_amount ?? "1000"))}
      ${field("max_amount", "Largest amount (KES)", num("max_amount", pr?.max_amount ?? "100000"))}
      ${field("min_term_months", "Shortest term (months)", num("min_term_months", pr?.min_term_months ?? 1))}
      ${field("max_term_months", "Longest term (months)", num("max_term_months", pr?.max_term_months ?? 12))}
      ${field("interest_method", "Interest method", html`<select name="interest_method">
        <option value="REDUCING_BALANCE" ${pr?.interest_method !== "FLAT" ? "selected" : ""}>Reducing balance</option>
        <option value="FLAT" ${pr?.interest_method === "FLAT" ? "selected" : ""}>Flat</option></select>`)}
      ${field("rate_basis", "Bracket rates are", html`<select name="rate_basis">
        ${[["ANNUAL", "Per year"], ["MONTHLY", "Per month"], ["PER_LOAN", "Per loan (flat)"]].map(([v, l]) => html`<option value="${v}" ${(pr?.rate_basis ?? "ANNUAL") === v ? "selected" : ""}>${l}</option>`)}</select>`)}
      ${field("funding_period_days", "Days open for funding", num("funding_period_days", pr?.funding_period_days ?? 14))}
      ${field("max_installment_share", "Most of spare income repayments may take (%)", num("max_installment_share", pr?.max_installment_share ?? "50"))}
      ${field("max_open_loans", "Open loans allowed per borrower", num("max_open_loans", pr?.max_open_loans ?? 1))}
      ${field("requires_guarantor", "Guarantor", html`<select name="requires_guarantor"><option value="true" ${pr?.requires_guarantor !== false ? "selected" : ""}>Required</option><option value="false" ${pr?.requires_guarantor === false ? "selected" : ""}>Not required</option></select>`)}
    </div>
    <fieldset class="choices choices--inline"><legend>Repayment frequencies</legend>
      ${Object.entries(FREQ).map(([k, l]) => html`<label class="check"><input type="checkbox" name="frequencies" value="${k}" ${(pr?.frequencies ?? ["MONTHLY"]).includes(k) ? "checked" : ""}><span>${l}</span></label>`)}
      <small class="field__error" data-for="frequencies"></small>
    </fieldset>
    <p class="form__error" data-error></p>
    <button class="btn" type="submit">${pr ? "Save product" : "Create product"}</button>
  </form>`;
}

function productsTab(host, _cfg, products, ctx) {
  mount(host, html`
    ${products.map((pr) => html`<section class="panel">
      <div class="panel__head"><h2>${pr.name}</h2>${pr.is_active ? html`<span class="tag tag--ok">Available</span>` : html`<span class="tag">Hidden</span>`}</div>
      <p class="muted small">${formatMoney(pr.min_amount)} to ${formatMoney(pr.max_amount)}, ${pr.min_term_months}–${pr.max_term_months} months, ${pr.interest_method_label.toLowerCase()}.</p>
      <details><summary>Edit</summary>${productForm(pr)}</details>
    </section>`)}
    <section class="panel"><details><summary>Add a loan product</summary>${productForm(null)}</details></section>`);
  $$(".product-form", host).forEach((form) => form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const d = Object.fromEntries(new FormData(form));
    d.frequencies = $$("input[name=frequencies]:checked", form).map((c) => c.value);
    d.is_active = d.is_active === "true";
    d.requires_guarantor = d.requires_guarantor === "true";
    const id = form.dataset.product;
    try {
      await busy(form.querySelector("button[type=submit]"), "Saving…", () =>
        (id === "new" ? api.post("admin/products/", d) : api.patch(`admin/products/${id}/`, d)));
      toast("Product saved", "ok");
      ctx.rerender();
    } catch (err) {
      if (!showFieldErrors(form, err)) form.querySelector("[data-error]").textContent = err.message;
    }
  }));
}

async function save(form, path, body, message, ctx, method = "put") {
  const err = form.querySelector("[data-error]");
  err.textContent = "";
  form.querySelectorAll(".field__error").forEach((e) => { e.textContent = ""; });
  if (!body.reason || body.reason.length < 10) {
    form.querySelector("[data-for=reason]").textContent = "Give a reason of at least 10 characters.";
    return;
  }
  try {
    await busy(form.querySelector("button[type=submit]"), "Saving…", () => api[method](path, body));
    toast(message, "ok");
    ctx.rerender();
  } catch (e) {
    if (!showFieldErrors(form, e)) err.textContent = e.message;
  }
}

// --- Fees, limits, offers, guarantees, extensions, overdue -------------------------------------

const FEE_LABELS = { deposit: "Deposit fee", withdrawal: "Withdrawal fee", transfer: "Transfer fee" };
const LIMIT_LABELS = {
  min_deposit: "Smallest deposit", max_deposit: "Largest deposit", min_withdrawal: "Smallest withdrawal",
  max_withdrawal: "Largest withdrawal", withdrawal_approval_threshold: "Withdrawals from this amount need approval",
  daily_withdrawal_limit: "Daily withdrawal limit", min_investment: "Smallest investment", min_transfer: "Smallest transfer",
};

function platformTab(host, _cfg, data, ctx) {
  const p = data.parameters;
  const sel = (name, value, options) => html`<select name="${name}">${Object.entries(options).map(([k, l]) => html`<option value="${k}" ${String(k) === String(value) ? "selected" : ""}>${l}</option>`)}</select>`;
  mount(host, html`<section class="panel">
    <h2>Fees, limits & offers (version ${data.version})</h2>
    <p class="panel__text">Every charge is shown to customers before they confirm. Amounts in KES.</p>
    <form id="platform-form" class="form" novalidate>
      <h3>Fees</h3>
      ${Object.entries(FEE_LABELS).map(([k, l]) => html`<div class="grid-fields">
        ${field(`f_${k}_type`, l, sel(`f_${k}_type`, p.fees[k].type, { FIXED: "Fixed amount", PERCENT: "Percentage" }))}
        ${field(`f_${k}_value`, "Amount or %", num(`f_${k}_value`, p.fees[k].value))}
        ${field(`f_${k}_min`, "Minimum (for %)", num(`f_${k}_min`, p.fees[k].min))}
        ${field(`f_${k}_max`, "Maximum (0 = none)", num(`f_${k}_max`, p.fees[k].max))}</div>`)}
      <div class="grid-fields">${field("account_fee", "Monthly account fee (0 = none)", num("account_fee", p.fees.account_management_monthly))}</div>
      <h3>Limits</h3>
      <div class="grid-fields">${Object.entries(LIMIT_LABELS).map(([k, l]) => field(`l_${k}`, l, num(`l_${k}`, p.limits[k])))}</div>
      <h3>How collected interest is shared (must add up to 100)</h3>
      <div class="grid-fields">
        ${field("s_investors", "Investors %", num("s_investors", p.revenue_split.investors))}
        ${field("s_platform", "Platform %", num("s_platform", p.revenue_split.platform))}
        ${field("s_guarantor", "Guarantor %", num("s_guarantor", p.revenue_split.guarantor), "Goes to the platform when there's no guarantor.")}
      </div>
      <h3>Open-offers marketplace (loans without a guarantor)</h3>
      <div class="grid-fields">
        ${field("o_min_rate", "Lowest rate investors may offer", num("o_min_rate", p.offers.min_rate), "Same rate type as the interest brackets.")}
        ${field("o_max_rate", "Highest rate investors may offer", num("o_max_rate", p.offers.max_rate))}
        ${field("o_min_amount", "Smallest offer", num("o_min_amount", p.offers.min_amount))}
      </div>
      <h3>Guarantors</h3>
      <div class="grid-fields">
        ${field("g_lock", "Lock the borrower's interest in the guarantor's wallet", sel("g_lock", p.guarantee.lock_interest, { true: "Yes", false: "No" }))}
        ${field("g_mult", "Most a guarantor can cover (× monthly income)", num("g_mult", p.guarantee.max_exposure_income_multiple))}
      </div>
      <h3>Extensions</h3>
      <div class="grid-fields">
        ${field("e_rate", "Extra interest per 30 days (% of remaining principal)", num("e_rate", p.extension.additional_monthly_rate))}
        ${field("e_fixed", "Fixed fee", num("e_fixed", p.extension.fixed_fee))}
        ${field("e_pct", "Percentage fee (once)", num("e_pct", p.extension.percent_fee))}
        ${field("e_max", "Most extensions per loan", num("e_max", p.extension.max_extensions_per_loan))}
        ${field("e_days", "Longest extension (days)", num("e_days", p.extension.max_extension_days))}
        ${field("e_after", "Allowed once a payment is overdue", sel("e_after", p.extension.allow_after_due_date, { true: "Yes", false: "No" }))}
        ${field("e_consent", "Investor consent", sel("e_consent", p.extension.investor_consent, { NONE: "Not needed", NEGATIVE: "Approved unless most object", EXPLICIT: "Most must agree" }))}
        ${field("e_consent_days", "Days investors have to respond", num("e_consent_days", p.extension.consent_days))}
      </div>
      <h3>Overdue payments</h3>
      <div class="grid-fields">
        ${field("d_grace", "Grace days before a late fee", num("d_grace", p.overdue.grace_days))}
        ${field("d_type", "Late fee", sel("d_type", p.overdue.late_fee_type, { PERCENT: "% of the installment", FIXED: "Fixed amount" }))}
        ${field("d_value", "Late fee amount or %", num("d_value", p.overdue.late_fee_value))}
        ${field("d_default", "Default after this many days overdue", num("d_default", p.overdue.default_after_days))}
        ${field("d_remind", "Remind borrowers this many days before", num("d_remind", p.overdue.reminder_days_before))}
      </div>
      ${reasonField()}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save as version ${data.version + 1}</button>
    </form>
    ${history(data.history)}
  </section>`);
  const form = $("#platform-form", host);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = (n) => form[n].value.trim();
    const fee = (k) => ({ type: v(`f_${k}_type`), value: v(`f_${k}_value`), min: v(`f_${k}_min`), max: v(`f_${k}_max`) });
    const parameters = {
      fees: { deposit: fee("deposit"), withdrawal: fee("withdrawal"), transfer: fee("transfer"), account_management_monthly: v("account_fee") },
      limits: Object.fromEntries(Object.keys(LIMIT_LABELS).map((k) => [k, v(`l_${k}`)])),
      revenue_split: { investors: v("s_investors"), platform: v("s_platform"), guarantor: v("s_guarantor") },
      offers: { min_rate: v("o_min_rate"), max_rate: v("o_max_rate"), min_amount: v("o_min_amount") },
      guarantee: { lock_interest: v("g_lock") === "true", max_exposure_income_multiple: v("g_mult") },
      extension: {
        additional_monthly_rate: v("e_rate"), fixed_fee: v("e_fixed"), percent_fee: v("e_pct"),
        max_extensions_per_loan: v("e_max"), max_extension_days: v("e_days"), allow_after_due_date: v("e_after") === "true",
        investor_consent: v("e_consent"), consent_days: v("e_consent_days"),
      },
      overdue: { grace_days: v("d_grace"), late_fee_type: v("d_type"), late_fee_value: v("d_value"),
        default_after_days: v("d_default"), reminder_days_before: v("d_remind") },
    };
    await save(form, "admin/config/platform/", { parameters, reason: v("reason") }, "Fees and limits saved", ctx);
  });
}

// --- Scheduled jobs ------------------------------------------------------------------------------

const JOBS = {
  expire_funding: "Close funding rounds that ran out (refunds investors)",
  consent: "Decide extensions whose investor-consent window closed",
  overdue: "Reminders, overdue status, late fees and defaults",
  claims: "Collect guarantor claims from guarantors' wallets",
  account_fees: "Monthly account fee (if set above zero)",
  reconcile: "Check the books balance",
};

function jobsTab(host) {
  mount(host, html`<section class="panel">
    <h2>Scheduled jobs</h2>
    <p class="panel__text">On a server these run automatically (Celery beat, or <code>python manage.py run_scheduled_jobs</code> from cron or Windows Task Scheduler). You can also run them now. Each job is safe to run more than once.</p>
    <form id="jobs-form" class="form">
      ${Object.entries(JOBS).map(([k, l]) => html`<label class="check"><input type="checkbox" name="job" value="${k}" checked> ${l}</label>`)}
      <button class="btn" type="submit">Run selected jobs</button>
    </form>
    <pre class="code-out" id="jobs-out" hidden></pre>
  </section>`);
  const form = $("#jobs-form", host);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const jobs = $$("[name=job]:checked", form).map((c) => c.value);
    try {
      const out = await busy(form.querySelector("button"), "Running…", () => api.post("admin/jobs/run/", { jobs }));
      const pre = $("#jobs-out", host);
      pre.hidden = false;
      pre.textContent = JSON.stringify(out, null, 2);
      toast("Jobs finished", "ok");
    } catch (e) { toast(e.message, "error"); }
  });
}
