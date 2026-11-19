import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, emptyState, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";
import { pager } from "./pager.js";
import { download, idemKey, money, stats, statusTag } from "./shared.js";

const TABS = [["deposit", "Deposit", "wallet.deposit"], ["withdraw", "Withdraw", "wallet.withdraw"], ["transfer", "Send to someone", "wallet.transfer"]];

export async function walletView(el, ctx) {
  const page = ctx.query.get("page") || "1";
  const tab = ctx.query.get("tab") || TABS.find(([, , p]) => can(p))?.[0];
  mount(el, html`${pageHead("Wallet")}${loadingBlock()}`);
  const [w, tx, payments] = await Promise.all([
    api.get("wallet/"), api.get("wallet/transactions/", { page }), api.get("payments/", { page_size: 8 }),
  ]);
  const b = w.balances;
  const open = payments.results.filter((p) => ["PENDING", "PROCESSING", "AWAITING_APPROVAL"].includes(p.status));

  mount(el, html`
    ${pageHead("Wallet", "Money only reaches your wallet once the payment provider confirms it. Every charge is shown before you confirm.")}
    ${stats([
      ["Available", money(b.available), "Ready to invest, repay, send or withdraw"],
      ["Committed to loans", money(b.invested), "Investments and offers waiting for pay-out"],
      ["Locked for guarantees", money(b.locked), "The interest of loans you guarantee"],
      ["Withdrawals in progress", money(b.pending)],
      ...(Number(b.held) > 0 ? [["Held by our team", money(b.held), "Contact support"]] : []),
    ])}
    ${w.sandbox ? html`<p class="notice notice--warn"><strong>Test mode.</strong> The sandbox payment method moves no real money. Each payment waits until you press "Confirm" below, as if you'd entered your M-Pesa PIN.</p>` : ""}
    ${open.length ? html`<section class="panel"><h2>Payments in progress</h2>
      <div class="table-wrap table-wrap--flat"><table class="table table--plain">
      <thead><tr><th scope="col">What</th><th scope="col">Amount</th><th scope="col">Fee</th><th scope="col">Status</th><th scope="col">Started</th><th></th></tr></thead>
      <tbody>${open.map((p) => html`<tr>
        <td>${p.purpose_label}<span class="sub">${p.provider_label}${p.loan ? `, loan ${p.loan}` : ""}</span></td>
        <td class="nowrap">${money(p.amount)}</td><td class="nowrap">${money(p.fee)}</td>
        <td>${statusTag(p.status, p.status_label)}</td><td class="nowrap">${formatDateTime(p.created_at)}</td>
        <td class="nowrap">
          ${p.can_confirm_in_sandbox ? html`<button class="btn btn--small" data-confirm="${p.id}">Confirm</button>
            <button class="btn btn--quiet btn--small" data-fail="${p.id}">Fail</button>` : ""}
          ${(p.status === "PENDING" && p.direction === "IN") || p.status === "AWAITING_APPROVAL" ? html`<button class="btn btn--quiet btn--small" data-cancel="${p.id}">Cancel</button>` : ""}
        </td></tr>`)}</tbody></table></div></section>` : ""}

    <section class="panel">
      <nav class="tabs" aria-label="Move money">${TABS.filter(([, , p]) => can(p)).map(([k, l]) => html`<a class="tabs__tab" href="#/wallet?tab=${k}" ${k === tab ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
      <div id="money-form"></div>
    </section>

    <section class="panel">
      <div class="panel__head"><h2>Transactions</h2>
        <button class="btn btn--quiet btn--small" type="button" id="statement">Download statement (CSV)</button></div>
      ${tx.results.length ? html`<div class="table-wrap table-wrap--flat"><table class="table table--plain">
        <thead><tr><th scope="col">When</th><th scope="col">What</th><th scope="col">Balance</th><th scope="col" class="num">Amount</th><th scope="col" class="num">Balance after</th></tr></thead>
        <tbody>${tx.results.map((t) => html`<tr>
          <td class="nowrap">${formatDateTime(t.at)}</td>
          <td>${t.memo}<span class="sub">${t.kind_label} · ${t.reference}</span></td>
          <td class="small">${t.account_label}</td>
          <td class="num nowrap ${String(t.amount).startsWith("-") ? "bad-text" : "ok-text"}">${money(t.amount)}</td>
          <td class="num nowrap">${money(t.balance_after)}</td></tr>`)}</tbody></table></div>${pager(tx, Number(page))}`
      : emptyState("No transactions yet", "Deposits, investments, repayments and fees will all appear here.")}
    </section>`);

  const formHost = $("#money-form", el);
  if (tab === "deposit") depositForm(formHost, w, ctx);
  if (tab === "withdraw") withdrawForm(formHost, w, ctx);
  if (tab === "transfer") transferForm(formHost, w, ctx);

  $("#statement", el).addEventListener("click", () => download("/api/v1/wallet/statement.csv", "p2plend-statement.csv"));
  $$("[data-page]", el).forEach((btn) => btn.addEventListener("click", () => ctx.navigate("/wallet", { tab, page: btn.dataset.page })));
  const act = async (btn, label, fn) => {
    try { await busy(btn, label, fn); ctx.rerender(); } catch (err) { toast(err.message, "error"); }
  };
  $$("[data-confirm]", el).forEach((btn) => btn.addEventListener("click", () => act(btn, "…", async () => {
    await api.post(`payments/${btn.dataset.confirm}/sandbox-confirm/`, { succeed: true }); toast("Payment confirmed", "ok");
  })));
  $$("[data-fail]", el).forEach((btn) => btn.addEventListener("click", () => act(btn, "…", async () => {
    await api.post(`payments/${btn.dataset.fail}/sandbox-confirm/`, { succeed: false }); toast("Payment marked as failed");
  })));
  $$("[data-cancel]", el).forEach((btn) => btn.addEventListener("click", () => act(btn, "…", async () => {
    await api.post(`payments/${btn.dataset.cancel}/cancel/`); toast("Payment cancelled");
  })));
}

/** Providers to choose from. Withdrawals only list the ones that can pay money out. */
const providerSelect = (w, payoutOnly = false) => html`<select name="provider">${w.providers
  .filter((p) => !payoutOnly || p.payout)
  .map((p) => html`<option value="${p.code}">${p.label}</option>`)}</select>`;

/** Live fee preview under the amount field. */
function wireQuote(form, kind, out) {
  let timer;
  form.amount.addEventListener("input", () => {
    clearTimeout(timer);
    const amount = form.amount.value.trim();
    if (!/^\d+(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) { out.textContent = ""; return; }
    timer = setTimeout(async () => {
      try {
        const q = await api.post("wallet/fees/quote/", { kind, amount });
        out.textContent = kind === "deposit"
          ? `Fee ${money(q.fee)}. ${money(q.you_receive)} will reach your wallet.`
          : `Fee ${money(q.fee)}. ${money(q.total_charged)} will leave your available balance.`;
      } catch { out.textContent = ""; }
    }, 300);
  });
}

async function submit(form, path, body, done) {
  clearFieldErrors(form);
  const err = form.querySelector("[data-error]");
  err.textContent = "";
  try {
    const result = await busy(form.querySelector("button[type=submit]"), "Sending…", () => api.post(path, body));
    done(result);
  } catch (e) {
    if (!showFieldErrors(form, e)) err.textContent = e.message;
  }
}

function depositForm(host, w, ctx) {
  if (!w.providers.length) {
    mount(host, html`<p class="notice">No payment method is switched on for this server yet. An administrator needs to configure M-Pesa (or enable the sandbox for testing).</p>`);
    return;
  }
  mount(host, html`<form class="form" id="deposit-form" novalidate>
    <div class="form__row">
      ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" required>`, `Between ${money(w.limits.min_deposit)} and ${money(w.limits.max_deposit)}.`)}
      ${field("provider", "Pay with", providerSelect(w))}
      ${field("phone_number", "M-Pesa number", html`<input name="phone_number" inputmode="tel" placeholder="Your verified number">`, "For M-Pesa you'll get a prompt on this phone.")}
    </div>
    <p class="small" data-quote></p><p class="form__error" data-error></p>
    <button class="btn" type="submit">Deposit</button></form>`);
  const form = $("#deposit-form", host);
  wireQuote(form, "deposit", form.querySelector("[data-quote]"));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    submit(form, "wallet/deposit/", { amount: form.amount.value.trim(), provider: form.provider.value,
      phone_number: form.phone_number.value.trim(), idempotency_key: idemKey() }, (p) => {
      // Card and checkout providers send the customer to their payment page, which returns to the wallet.
      if (p.checkout_url) {
        window.location.href = p.checkout_url;
        return;
      }
      toast(p.provider === "SANDBOX" ? "Deposit started. Confirm it under 'Payments in progress'." : "Check your phone and enter your M-Pesa PIN.", "ok");
      ctx.rerender();
    });
  });
}

function withdrawForm(host, w, ctx) {
  mount(host, html`<form class="form" id="withdraw-form" novalidate>
    <div class="form__row">
      ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" required>`,
        `From ${money(w.limits.min_withdrawal)}. Amounts from ${money(w.limits.withdrawal_approval_threshold)} are checked by our team first.`)}
      ${field("provider", "Send to", providerSelect(w, true), "M-Pesa withdrawals go to your verified phone number.")}
    </div>
    <p class="small" data-quote></p><p class="form__error" data-error></p>
    <button class="btn" type="submit">Withdraw</button></form>`);
  const form = $("#withdraw-form", host);
  wireQuote(form, "withdrawal", form.querySelector("[data-quote]"));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    submit(form, "wallet/withdraw/", { amount: form.amount.value.trim(), provider: form.provider.value, idempotency_key: idemKey() }, (p) => {
      toast(p.status === "AWAITING_APPROVAL" ? "Withdrawal sent for approval" : "Withdrawal on its way", "ok");
      ctx.rerender();
    });
  });
}

function transferForm(host, w, ctx) {
  mount(host, html`<form class="form" id="transfer-form" novalidate>
    <div class="form__row">
      ${field("recipient_email", "Their email", html`<input name="recipient_email" type="email" required>`, "They need a P2P Lend account.")}
      ${field("amount", "Amount (KES)", html`<input name="amount" inputmode="decimal" required>`, `From ${money(w.limits.min_transfer)}.`)}
      ${field("note", "Note (optional)", html`<input name="note" maxlength="140">`)}
    </div>
    <p class="small" data-quote></p><p class="form__error" data-error></p>
    <button class="btn" type="submit">Send</button></form>`);
  const form = $("#transfer-form", host);
  wireQuote(form, "transfer", form.querySelector("[data-quote]"));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!window.confirm(`Send KES ${form.amount.value.trim()} to ${form.recipient_email.value.trim()}? Transfers can't be reversed.`)) return;
    submit(form, "wallet/transfer/", { recipient_email: form.recipient_email.value.trim(), amount: form.amount.value.trim(),
      note: form.note.value.trim(), idempotency_key: idemKey() }, () => { toast("Money sent", "ok"); ctx.rerender(); });
  });
}
