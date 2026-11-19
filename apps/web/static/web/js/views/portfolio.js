import { api } from "../api.js";
import { $, $$, formatDate, html, mount, toast } from "../ui.js";
import { busy, emptyState, loadingBlock, pageHead, riskTag } from "./common.js";
import { openDrawer } from "./drawer.js";
import { pager } from "./pager.js";
import { download, money, rateText, stats, statusTag } from "./shared.js";

export async function portfolioView(el, ctx) {
  const page = ctx.query.get("page") || "1";
  const status = ctx.query.get("status") || "";
  mount(el, html`${pageHead("Portfolio")}${loadingBlock()}`);
  const [p, inv, offers] = await Promise.all([
    api.get("portfolio/"), api.get("investments/", { page, status }), api.get("offers/", { page_size: 50 }),
  ]);
  const votes = inv.results.filter((i) => i.pending_extension);
  const openOffers = offers.results.filter((o) => o.status === "OPEN");

  mount(el, html`
    ${pageHead("Portfolio", "Every loan you've funded. Repayments reach your wallet as soon as borrowers pay, shared by how much you put in.")}
    ${stats([
      ["Lent and still owed to you", money(p.outstanding_principal), `${money(p.at_risk)} of it in overdue or defaulted loans`],
      ["Earned so far", money(p.total_earned), `${p.return_percent}% of everything you've invested`],
      ["Principal returned", money(p.principal_repaid), Number(p.recovered) > 0 ? `plus ${money(p.recovered)} recovered from guarantors` : ""],
      ["Waiting for pay-out", money(p.committed), "Committed to loans still filling up"],
    ])}
    ${votes.length ? html`<section class="panel panel--feature"><h2>Extensions waiting for your answer</h2>
      ${votes.map((i) => { const e = i.pending_extension; return html`<div class="vote">
        <p><strong>${i.loan}</strong>: the borrower asks for ${e.days} more days (“${e.reason}”). You'd share ${money(e.extension_interest)} extra interest.
        ${e.mode === "NEGATIVE" ? "It's approved unless investors holding most of the loan object" : "It needs investors holding most of the loan to agree"} by ${formatDate(e.deadline)}.</p>
        ${e.my_vote === null ? html`<p><button class="btn btn--small" data-vote="${e.id}" data-agree="1">Agree</button>
          <button class="btn btn--quiet btn--small" data-vote="${e.id}" data-agree="0">Object</button></p>`
          : html`<p class="small">You ${e.my_vote ? "agreed" : "objected"}. You can change your answer: <button class="btn btn--quiet btn--small" data-vote="${e.id}" data-agree="${e.my_vote ? 0 : 1}">${e.my_vote ? "Object instead" : "Agree instead"}</button></p>`}
      </div>`; })}</section>` : ""}
    ${openOffers.length ? html`<section class="panel"><h2>Your open offers</h2><table class="table table--plain">
      <thead><tr><th scope="col">Loan</th><th scope="col" class="num">Amount (held)</th><th scope="col" class="num">Rate</th><th scope="col">Made</th><th></th></tr></thead>
      <tbody>${openOffers.map((o) => html`<tr><td>${o.loan}</td><td class="num">${money(o.amount)}</td><td class="num">${o.rate}%</td><td>${formatDate(o.created_at)}</td>
        <td><a class="btn btn--quiet btn--small" href="#/marketplace?mode=OFFERS">Change</a> <button class="btn btn--quiet btn--small" data-withdraw-offer="${o.id}">Withdraw</button></td></tr>`)}</tbody></table></section>` : ""}
    <section class="panel">
      <div class="panel__head"><h2>Investments</h2>
        <div><select id="status-filter" aria-label="Status">${[["", "All"], ["COMMITTED", "Waiting for pay-out"], ["ACTIVE", "Active"], ["COMPLETED", "Repaid"], ["DEFAULTED", "In default"], ["REFUNDED", "Returned"]].map(([v, l]) => html`<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`)}</select>
        <button class="btn btn--quiet btn--small" id="returns-csv">Returns statement (CSV)</button></div></div>
      ${inv.results.length ? html`<div class="table-wrap table-wrap--flat"><table class="table table--plain">
        <thead><tr><th scope="col">Loan</th><th scope="col" class="num">Put in</th><th scope="col">Rate</th><th scope="col" class="num">Still owed</th><th scope="col" class="num">Earned</th><th scope="col">Status</th><th></th></tr></thead>
        <tbody>${inv.results.map((i, n) => html`<tr>
          <td>${i.loan}<span class="sub">${i.share_percent}% of the loan · ${riskTag(i.risk_class)}</span></td>
          <td class="num nowrap">${money(i.amount)}</td><td class="nowrap">${rateText(i.rate, i.rate_basis)}</td>
          <td class="num nowrap">${money(i.outstanding)}</td><td class="num nowrap">${money(i.total_earned)}</td>
          <td>${statusTag(i.status, i.status_label)}<span class="sub">Loan: ${i.loan_status_label}</span></td>
          <td class="nowrap"><button class="btn btn--quiet btn--small" data-detail="${n}">Payments</button>
            ${i.status === "COMMITTED" && ["PUBLISHED", "PARTIALLY_FUNDED"].includes(i.loan_status) ? html`<button class="btn btn--quiet btn--small" data-withdraw="${i.id}">Take back</button>` : ""}</td></tr>`)}</tbody></table></div>
        ${pager(inv, Number(page))}`
      : emptyState("No investments yet", "Loans you fund from the marketplace appear here.", { href: "#/marketplace", label: "Open the marketplace" })}
    </section>`);

  $("#status-filter", el).addEventListener("change", (ev) => ctx.navigate("/portfolio", { status: ev.target.value }));
  $("#returns-csv", el).addEventListener("click", () => download("/api/v1/investments/statement.csv", "p2plend-returns.csv"));
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/portfolio", { status, page: b.dataset.page })));
  const run = async (btn, fn, msg) => { try { await busy(btn, "…", fn); toast(msg, "ok"); ctx.rerender(); } catch (e) { toast(e.message, "error"); } };
  $$("[data-vote]", el).forEach((b) => b.addEventListener("click", () => run(b, () => api.post(`extensions/${b.dataset.vote}/vote/`, { agrees: b.dataset.agree === "1" }), "Answer recorded")));
  $$("[data-withdraw]", el).forEach((b) => b.addEventListener("click", () => {
    if (window.confirm("Take this money back? It returns to your available balance.")) run(b, () => api.post(`investments/${b.dataset.withdraw}/withdraw/`), "Investment withdrawn");
  }));
  $$("[data-withdraw-offer]", el).forEach((b) => b.addEventListener("click", () => run(b, () => api.del(`offers/${b.dataset.withdrawOffer}/`), "Offer withdrawn")));
  $$("[data-detail]", el).forEach((b) => b.addEventListener("click", async () => {
    const i = inv.results[Number(b.dataset.detail)];
    const rows = await api.get(`investments/${i.id}/distributions/`);
    openDrawer(html`<h2 id="drawer-title">${i.loan}</h2><p class="muted">${money(i.amount)} at ${rateText(i.rate, i.rate_basis)}</p>
      ${rows.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Date</th><th scope="col" class="num">Principal</th><th scope="col" class="num">Interest</th><th scope="col" class="num">Total</th></tr></thead>
        <tbody>${rows.map((r) => html`<tr><td>${formatDate(r.at)}${r.recovery ? html`<span class="sub">From the guarantor</span>` : ""}</td><td class="num">${money(r.principal)}</td>
          <td class="num">${money((Number(r.interest) + Number(r.extension_interest)).toFixed(2))}</td><td class="num"><strong>${money(r.total)}</strong></td></tr>`)}</tbody></table>`
        : html`<p class="muted">Nothing received yet.</p>`}`);
  }));
}
