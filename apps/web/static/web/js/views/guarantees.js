import { api } from "../api.js";
import { can } from "../session.js";
import { $$, formatDate, html, mount, toast } from "../ui.js";
import { busy, emptyState, loadingBlock, pageHead, riskTag } from "./common.js";
import { money, rateText, stats, statusTag } from "./shared.js";

export async function guaranteesView(el, ctx) {
  mount(el, html`${pageHead("Guarantees")}${loadingBlock()}`);
  const [data, wallet] = await Promise.all([api.get("guarantees/"), api.get("wallet/")]);
  const requests = data.guarantees.filter((g) => g.status === "REQUESTED");
  const others = data.guarantees.filter((g) => g.status !== "REQUESTED");
  const claims = data.guarantees.filter((g) => g.claim && ["OPEN", "PARTLY_RECOVERED"].includes(g.claim.status));

  mount(el, html`
    ${pageHead("Guarantees", "When you guarantee a loan, the borrower's total interest is locked in your wallet until they've paid it. If the loan defaults, you cover what investors are still owed. You earn a share of the interest the borrower pays.")}
    ${stats([
      ["Currently guaranteeing", money(data.exposure)],
      ["Locked in your wallet", money(wallet.balances.locked)],
      ["Available", money(wallet.balances.available)],
      ["Commission earned", money(String(data.commission_total))],
    ])}
    ${claims.length ? html`<section class="panel panel--feature"><h2>Claims against you</h2>
      ${claims.map((g) => html`<div class="vote"><p><strong>${g.loan}</strong> defaulted. You owe investors ${money(g.claim.outstanding)} (of ${money(g.claim.amount)}).
        Money in your available balance is used automatically each day; you can pay now.</p>
        <button class="btn btn--small" data-pay="${g.id}">Pay from my wallet now</button> <a class="btn btn--quiet btn--small" href="#/wallet?tab=deposit">Deposit</a></div>`)}</section>` : ""}
    <section class="panel"><h2>Requests</h2>
      ${requests.length ? requests.map((g) => {
        const short = Number(wallet.balances.available) < Number(g.interest_to_lock);
        const waiting = !g.can_accept;
        return html`<article class="request">
          <h3>${g.borrower} asks you to guarantee ${money(g.amount)}</h3>
          <table class="kv">
            <tr><th scope="row">Loan</th><td>${g.loan}, ${g.purpose.toLowerCase()}, ${g.term_months} months at ${rateText(g.rate, g.rate_basis)}</td></tr>
            <tr><th scope="row">Borrower</th><td>Trust score ${g.trust_score ?? "–"} · ${riskTag(g.risk_class)}</td></tr>
            <tr><th scope="row">You'd cover</th><td>Up to ${money(g.coverage_amount)} if it defaults</td></tr>
            <tr><th scope="row">Locked from your wallet</th><td><strong>${money(g.interest_to_lock)}</strong> (the borrower's total interest), released once they've paid it</td></tr>
          </table>
          ${!waiting && short ? html`<p class="notice notice--warn">You need ${money(g.interest_to_lock)} available to accept. <a href="#/wallet?tab=deposit">Deposit</a></p>` : ""}
          ${can("guarantees.respond") ? html`<p><button class="btn btn--small" data-accept="${g.id}" ${short || waiting ? "disabled" : ""}>Accept and lock ${money(g.interest_to_lock)}</button>
            <button class="btn btn--quiet btn--small" data-decline="${g.id}">Decline</button>
            ${can("chat.use") ? html`<button class="btn btn--quiet btn--small" data-chat="${g.loan_id}">Message the borrower</button>` : ""}</p>` : ""}
        </article>`;
      }) : html`<p class="muted">No requests waiting.</p>`}
    </section>
    <section class="panel"><h2>Your guarantees</h2>
      ${others.length ? html`<div class="table-wrap table-wrap--flat"><table class="table table--plain">
        <thead><tr><th scope="col">Loan</th><th scope="col">Borrower</th><th scope="col" class="num">Amount</th><th scope="col" class="num">Locked</th><th scope="col" class="num">Earned</th><th scope="col">Status</th><th></th></tr></thead>
        <tbody>${others.map((g) => html`<tr><td>${g.loan}<span class="sub">${g.loan_status_label}</span></td><td>${g.borrower}</td>
          <td class="num">${money(g.amount)}</td>
          <td class="num">${money(g.locked_amount)}${g.lock_released_at ? html`<span class="sub">Released ${formatDate(g.lock_released_at)}</span>` : ""}</td>
          <td class="num">${money(g.commission_earned)}</td><td>${statusTag(g.status, g.status_label)}</td>
          <td>${g.status === "ACCEPTED" && ["PUBLISHED", "PARTIALLY_FUNDED", "FULLY_FUNDED", "GUARANTOR_PENDING", "READY_FOR_DISBURSEMENT"].includes(g.loan_status) ? html`<button class="btn btn--quiet btn--small" data-withdraw="${g.id}">Withdraw</button>` : ""}</td></tr>`)}</tbody></table></div>`
      : emptyState("No guarantees yet", "Requests from borrowers who name you as their guarantor appear here.")}
    </section>`);

  const run = async (btn, fn, msg) => { try { await busy(btn, "…", fn); toast(msg, "ok"); ctx.rerender(); } catch (e) { toast(e.message, "error"); } };
  $$("[data-accept]", el).forEach((b) => b.addEventListener("click", () => {
    const g = requests.find((x) => x.id === b.dataset.accept);
    if (window.confirm(`Guarantee ${g.loan}? ${money(g.interest_to_lock)} will be locked in your wallet until the borrower has paid the interest, and you may have to cover up to ${money(g.coverage_amount)} if the loan defaults.`))
      run(b, () => api.post(`guarantees/${g.id}/respond/`, { accept: true }), "Guarantee accepted");
  }));
  $$("[data-decline]", el).forEach((b) => b.addEventListener("click", () => {
    const note = window.prompt("Decline this request. Optional note for the borrower:", "");
    if (note !== null) run(b, () => api.post(`guarantees/${b.dataset.decline}/respond/`, { accept: false, note }), "Request declined");
  }));
  $$("[data-withdraw]", el).forEach((b) => b.addEventListener("click", () => {
    const note = window.prompt("Withdraw your guarantee? The locked money is released. Optional note:", "");
    if (note !== null) run(b, () => api.post(`guarantees/${b.dataset.withdraw}/withdraw/`, { note }), "Guarantee withdrawn");
  }));
  $$("[data-pay]", el).forEach((b) => b.addEventListener("click", () => run(b, () => api.post(`guarantees/${b.dataset.pay}/pay-claim/`), "Payment applied")));
  $$("[data-chat]", el).forEach((b) => b.addEventListener("click", async () => {
    try { const c = await api.post("chat/", { loan_id: b.dataset.chat }); ctx.navigate(`/chat/${c.id}`); } catch (e) { toast(e.message, "error"); }
  }));
}

export async function commissionsView(el) {
  mount(el, html`${pageHead("Commissions")}${loadingBlock()}`);
  const data = await api.get("guarantees/");
  const rows = data.guarantees.filter((g) => Number(g.commission_earned) > 0 || g.status === "ACCEPTED");
  mount(el, html`${pageHead("Commissions", "Your share of the interest borrowers pay on loans you guarantee. It's paid into your wallet with each repayment, and stops if a loan defaults.")}
    ${stats([["Total earned", money(String(data.commission_total))]])}
    <section class="panel">${rows.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Loan</th><th scope="col">Borrower</th><th scope="col">Status</th><th scope="col" class="num">Earned</th></tr></thead>
      <tbody>${rows.map((g) => html`<tr><td>${g.loan}</td><td>${g.borrower}</td><td>${statusTag(g.status, g.status_label)}</td><td class="num">${money(g.commission_earned)}</td></tr>`)}</tbody></table>`
      : emptyState("Nothing earned yet", "Commission starts with the first repayment on a loan you guarantee.")}</section>`);
}
