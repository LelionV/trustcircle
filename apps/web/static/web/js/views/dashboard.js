import { api } from "../api.js";
import { can, user } from "../session.js";
import { $, formatDate, formatDateTime, formatMoney, greeting, html, mount } from "../ui.js";
import { actionName, checklist, emptyState, errorBlock, loadingBlock, loanTag, pageHead } from "./common.js";
import { layoutRuler, ruler } from "./ruler.js";
import { money, rateText, stats } from "./shared.js";

export async function dashboardView(el) {
  const u = user();
  if (can("admin.dashboard.view")) return adminOverview(el);
  if (u.role === "BORROWER") return borrowerDashboard(el, u);
  if (u.role === "INVESTOR") return investorDashboard(el, u);
  if (u.role === "GUARANTOR") return guarantorDashboard(el, u);
  return mount(el, html`${pageHead(`${greeting()}, ${u.first_name || u.full_name}`)}
    <section class="panel">
      <h2>No administrator level yet</h2>
      <p>Your account is an administrator account without a permission level, so there is nothing to manage yet.
      A super admin can give you Support, Operations, Finance or Super access.</p>
      <a class="btn btn--quiet" href="#/profile">View your profile</a>
    </section>`);
}

const firstName = (u) => u.first_name || u.full_name;

/** Real progress through verification; each open step links to where it's done. */
function verificationSteps(u, profileComplete, last) {
  const kyc = u.kyc_status;
  return [
    { title: "Verify your email", detail: u.is_email_verified ? u.email : html`We'll send a code to your inbox. <a href="#/profile">Verify now</a>`,
      state: u.is_email_verified ? "done" : "todo" },
    { title: "Verify your phone number", detail: u.is_phone_verified ? u.phone_number
      : html`Needed for M-Pesa payments and alerts. <a href="#/profile">${u.phone_number ? "Verify now" : "Add your number"}</a>`,
      state: u.is_phone_verified ? "done" : "todo" },
    { title: "Tell us about yourself", detail: profileComplete ? "Work, income and location saved" : html`Work, income and where you live. <a href="#/profile">Fill in</a>`,
      state: profileComplete ? "done" : "todo" },
    { title: "Verify your identity",
      detail: { APPROVED: "Documents approved", PENDING: "Waiting for our team to review your documents.",
        REJECTED: html`Your documents were rejected. <a href="#/kyc">See why and resubmit</a>`,
        NOT_SUBMITTED: html`Upload your ID and a selfie. <a href="#/kyc">Start</a>` }[kyc],
      state: kyc === "APPROVED" ? "done" : kyc === "PENDING" ? "later" : "todo" },
    last,
  ];
}

async function bracketPanel(el, { title, text, score }) {
  const host = $("#brackets", el);
  try {
    const set = await api.get("pricing/brackets/");
    const marker = score === undefined ? null
      : score === null ? { score: set.new_borrower_score, label: "New borrowers start here" }
        : { score, label: `You: ${score}` };
    mount(host, html`<h2>${title}</h2>
      ${ruler(set, { marker })}
      <p class="panel__text">${text}</p>
      ${set.you?.next ? html`<p><strong>Reach ${set.you.next.min_score}</strong> (${set.you.next.points_needed} more points) to borrow at ${set.you.next.annual_rate}% next time. <a href="#/trust">How</a></p>` : ""}`);
    layoutRuler(host);
  } catch (err) {
    mount(host, html`<h2>${title}</h2>${errorBlock(err)}`);
  }
}

async function borrowerDashboard(el, u) {
  mount(el, html`${pageHead(`${greeting()}, ${firstName(u)}`)}${loadingBlock()}`);
  const [profile, loans, trust] = await Promise.all([api.get("accounts/me/profile/"), api.get("loans/"), api.get("trust/me/")]);
  const open = loans.filter((l) => !["CANCELLED", "REJECTED", "COMPLETED"].includes(l.status));
  const ready = u.kyc_status === "APPROVED" && u.is_email_verified && u.is_phone_verified;
  mount(el, html`
    ${pageHead(`${greeting()}, ${firstName(u)}`, "Your trust score sets your interest rate. Repay early and on time and your next loan costs less.")}
    <section class="panel panel--feature" id="brackets">${loadingBlock("Loading interest brackets")}</section>
    <div class="columns">
      <section class="panel">
        <h2>${ready ? "Your account" : "Before your first loan"}</h2>
        ${checklist(verificationSteps(u, profile.profile?.is_complete, {
          title: "Apply for a loan", detail: ready ? html`See your rate before you submit. <a href="#/apply">Apply</a>` : "Opens once the steps above are done.",
          state: loans.some((l) => l.status !== "DRAFT" && l.status !== "CANCELLED") ? "done" : ready ? "todo" : "later",
        }))}
      </section>
      <section class="panel">
        <h2>Your loans</h2>
        ${open.length ? html`<ul class="activity">${open.map((l) => html`<li>
            <a class="activity__what" href="#/loans/${l.id}">${l.reference}, ${formatMoney(l.amount)}</a>
            <p class="activity__meta">${loanTag(l.status, l.status_label)} ${l.annual_rate ? rateText(l.annual_rate, l.rate_basis) : ""}
              ${l.outstanding?.next_due_date ? html`<span class="sub">Next: ${money(l.outstanding.next_due_amount)} on ${formatDate(l.outstanding.next_due_date)}</span>` : ""}</p></li>`)}</ul>
            <a class="btn btn--quiet" href="#/loans">All loans</a>`
          : emptyState("No loans yet", ready ? "Apply when you're ready; you'll see the full cost first." : "Finish verification to apply.",
            ready ? { href: "#/apply", label: "Apply for a loan" } : null)}
      </section>
    </div>`);
  return bracketPanel(el, {
    title: trust.is_scored ? `Your trust score is ${trust.score}` : "Where your rate comes from",
    score: trust.is_scored ? trust.score : null,
    text: trust.is_scored
      ? "Each installment paid early moves you right and each late one moves you left. A better bracket applies to your next loan; a loan you already have keeps its rate."
      : "You get a score once your identity is verified. New borrowers start in the middle and move up as they repay on time.",
  });
}

async function investorDashboard(el, u) {
  mount(el, html`${pageHead(`${greeting()}, ${firstName(u)}`)}${loadingBlock()}`);
  const [profile, market, offers, wallet, portfolio] = await Promise.all([api.get("accounts/me/profile/"), api.get("marketplace/"),
    api.get("marketplace/", { mode: "OFFERS" }), api.get("wallet/"), api.get("portfolio/")]);
  mount(el, html`
    ${pageHead(`${greeting()}, ${firstName(u)}`, "Fund part or all of a loan and earn interest as borrowers repay.")}
    <section class="panel panel--feature" id="brackets">${loadingBlock("Loading interest brackets")}</section>
    <div class="columns">
      <section class="panel">
        <h2>Before you invest</h2>
        ${checklist(verificationSteps(u, profile.profile?.is_complete, {
          title: "Deposit funds", detail: html`Top up your wallet. <a href="#/wallet?tab=deposit">Deposit</a>`,
          state: Number(wallet.balances.available) + Number(wallet.balances.invested) > 0 || Number(portfolio.total_invested) > 0 ? "done" : "todo",
        }))}
      </section>
      <section class="panel">
        <h2>Your money</h2>
        ${stats([["Available", money(wallet.balances.available)], ["Lent and owed to you", money(portfolio.outstanding_principal)], ["Earned", money(portfolio.total_earned)]])}
        <h2>Open for funding</h2>
        <p><a href="#/marketplace">${market.count} guaranteed loan${market.count === 1 ? "" : "s"}</a> and
          <a href="#/marketplace?mode=OFFERS">${offers.count} open-offer loan${offers.count === 1 ? "" : "s"}</a> (no guarantor; you set the rate).</p>
      </section>
    </div>`);
  return bracketPanel(el, {
    title: "How borrowers are priced",
    text: "Borrowers with higher trust scores pay lower rates. Before you fund a loan you'll see the borrower's score, risk rating, income verification and guarantor.",
  });
}

async function guarantorDashboard(el, u) {
  const [profile, g, wallet] = await Promise.all([api.get("accounts/me/profile/"), api.get("guarantees/"), api.get("wallet/")]);
  const requests = g.guarantees.filter((x) => x.status === "REQUESTED");
  mount(el, html`
    ${pageHead(`${greeting()}, ${firstName(u)}`, "Back a borrower's loan and earn a commission from the interest they repay.")}
    <section class="panel panel--feature">
      <h2>How guaranteeing works</h2>
      <ol class="flow">
        <li><p class="flow__title">A borrower asks you</p><p>You see the amount, the repayment schedule, their trust score and risk rating, and exactly what you would owe if they default.</p></li>
        <li><p class="flow__title">You accept or decline</p><p>The loan can't be paid out until you accept. Accepting locks the borrower's total interest in your wallet until they've paid it.</p></li>
        <li><p class="flow__title">You earn as they repay</p><p>Your commission comes from interest actually collected. You're told straight away if a payment is late.</p></li>
      </ol>
    </section>
    <div class="columns">
      <section class="panel">
        <h2>Before you can guarantee</h2>
        ${checklist(verificationSteps(u, profile.profile?.is_complete, {
          title: "Respond to your first request", detail: html`<a href="#/guarantees">See requests</a>`, state: g.guarantees.some((x) => x.status !== "REQUESTED") ? "done" : "todo",
        }))}
      </section>
      <section class="panel">
        <h2>Guarantee requests</h2>
        ${stats([["Locked for guarantees", money(wallet.balances.locked)], ["Commission earned", money(String(g.commission_total))]])}
        ${requests.length ? html`<p>${requests.length} request${requests.length === 1 ? "" : "s"} waiting. <a class="btn btn--small" href="#/guarantees">Review</a></p>`
          : emptyState("No requests to answer", "Requests from borrowers who name you appear here. As a guarantor you can also invest from the marketplace.")}
      </section>
    </div>`);
}

async function adminOverview(el) {
  mount(el, html`${pageHead("Platform overview", "Figures update when you open this page.")}
    <div id="overview">${loadingBlock()}</div>`);
  const host = $("#overview", el);
  let data;
  try {
    data = await api.get("admin/overview/");
  } catch (err) {
    mount(host, errorBlock(err, "retry-overview"));
    $("#retry-overview", host)?.addEventListener("click", () => adminOverview(el));
    return;
  }
  const r = data.users_by_role;
  const ls = data.loans_by_status || {};
  const figures = [
    ["Active users", data.users_total],
    ["Borrowers", r.BORROWER],
    ["Investors", r.INVESTOR],
    ["Guarantors", r.GUARANTOR],
    ["KYC waiting", data.kyc_pending ?? 0],
    ["Frozen accounts", data.frozen_accounts],
  ];
  const pipeline = [
    ["New applications", (ls.SUBMITTED || 0), "#/admin/loans?status=SUBMITTED"],
    ["In review", ls.UNDER_REVIEW || 0, "#/admin/loans?status=UNDER_REVIEW"],
    ["Approved, not yet open", ls.APPROVED || 0, "#/admin/loans?status=APPROVED"],
    ["Open for funding", (ls.PUBLISHED || 0) + (ls.PARTIALLY_FUNDED || 0), "#/admin/loans?status=PUBLISHED"],
    ["Rejected", ls.REJECTED || 0, "#/admin/loans?status=REJECTED"],
  ];
  mount(host, html`
    <dl class="tally">
      ${figures.map(([label, n]) => html`<div class="tally__item"><dt>${label}</dt><dd>${Number(n).toLocaleString("en-KE")}</dd></div>`)}
    </dl>
    <div class="columns">
      <section class="panel">
        <h2>Loan pipeline</h2>
        <table class="kv">${pipeline.map(([label, n, href]) => html`<tr><th scope="row">${label}</th>
          <td>${can("admin.loans.view") && n ? html`<a href="${href}">${n}</a>` : n}</td></tr>`)}</table>
        <h3>Verification backlog</h3>
        <table class="kv">
          <tr><th scope="row">Identity documents waiting</th><td>${can("admin.kyc.view") && data.kyc_pending ? html`<a href="#/admin/kyc">${data.kyc_pending}</a>` : data.kyc_pending}</td></tr>
          <tr><th scope="row">Email not verified</th><td>${data.email_unverified}</td></tr>
          <tr><th scope="row">Phone not verified</th><td>${data.phone_unverified}</td></tr>
          <tr><th scope="row">Joined in the last 7 days</th><td>${data.joined_last_7_days}</td></tr>
        </table>
      </section>
      ${can("admin.audit.view") ? html`<section class="panel">
        <h2>Recent activity</h2>
        ${data.recent_audit.length
          ? html`<ul class="activity">${data.recent_audit.map((a) => html`<li>
              <p class="activity__what">${actionName(a.action)}</p>
              <p class="activity__meta">${a.actor_email || "System"}, ${formatDateTime(a.created_at)}</p>
              ${a.reason ? html`<p class="activity__reason">${a.reason}</p>` : ""}
            </li>`)}</ul>
            <a class="btn btn--quiet" href="#/admin/audit">Open audit trail</a>`
          : emptyState("No activity yet", "Administrator actions and configuration changes will be listed here.")}
      </section>` : ""}
    </div>
    <section class="panel">
      <h2>Money and loan book</h2>
      <table class="kv">
        <tr><th scope="row">Ready to pay out</th><td>${ls.READY_FOR_DISBURSEMENT ? html`<a href="#/admin/loans?status=READY_FOR_DISBURSEMENT">${ls.READY_FOR_DISBURSEMENT}</a>` : 0}</td></tr>
        <tr><th scope="row">Active loans</th><td>${(ls.ACTIVE || 0)}</td></tr>
        <tr><th scope="row">Overdue</th><td>${ls.OVERDUE ? html`<a href="#/admin/loans?status=OVERDUE">${ls.OVERDUE}</a>` : 0}</td></tr>
        <tr><th scope="row">Defaulted</th><td>${ls.DEFAULTED || 0}</td></tr>
        <tr><th scope="row">Repaid</th><td>${ls.COMPLETED || 0}</td></tr>
      </table>
      ${can("admin.reports.view") ? html`<a class="btn btn--quiet" href="#/admin/reports">Full reports</a>` : ""}
      ${can("admin.reconciliation.run") ? html` <a class="btn btn--quiet" href="#/admin/finance">Reconciliation</a>` : ""}
    </section>`);
}

