import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDate, formatDateTime, formatMoney, html, mount, toast } from "../ui.js";
import { busy, emptyState, field, kycTag, loadingBlock, pageHead, showFieldErrors } from "./common.js";
import { documentPreviews, wireDocuments } from "./documents.js";
import { pager } from "./pager.js";

const TABS = [["PENDING", "Waiting"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"]];

export async function adminKycListView(el, ctx) {
  const status = ctx.query.get("status") || "PENDING";
  const page = ctx.query.get("page") || "1";
  mount(el, html`${pageHead("KYC review")}${loadingBlock()}`);
  const data = await api.get("admin/kyc/", { status, page });
  mount(el, html`
    ${pageHead("KYC review", "Check identity documents. Oldest submissions first.")}
    <nav class="tabs" aria-label="Status">${TABS.map(([v, l]) => html`<a class="tabs__tab" href="#/admin/kyc?status=${v}" ${v === status ? html`aria-current="page"` : ""}>${l}</a>`)}</nav>
    ${data.results.length ? html`<div class="table-wrap"><table class="table">
      <thead><tr><th scope="col">Customer</th><th scope="col">Role</th><th scope="col">Document</th><th scope="col">Submitted</th><th scope="col">Status</th></tr></thead>
      <tbody>${data.results.map((k) => html`<tr>
        <td><a class="linkish" href="#/admin/kyc/${k.id}">${k.user.full_name}</a><span class="sub">${k.user.email}</span></td>
        <td>${k.user.role_label}</td>
        <td>${k.document_type_label}<span class="sub">${k.document_number}</span>${k.duplicate_document_users.length ? html`<span class="tag tag--bad">Also used by another account</span>` : ""}</td>
        <td class="nowrap">${formatDateTime(k.submitted_at)}</td>
        <td>${kycTag(k.status)}</td>
      </tr>`)}</tbody></table></div>${pager(data, Number(page))}`
    : html`<section class="panel">${emptyState(status === "PENDING" ? "Nothing waiting" : "No submissions", status === "PENDING" ? "New identity submissions will appear here." : "")}</section>`}`);
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/kyc", { status, page: b.dataset.page })));
}

export async function adminKycDetailView(el, ctx) {
  mount(el, html`${pageHead("KYC submission")}${loadingBlock()}`);
  const k = await api.get(`admin/kyc/${ctx.params.id}/`);
  const u = k.user;
  const p = u.profile || {};
  const canDecide = can("admin.kyc.approve") && k.status === "PENDING";
  const incomeRole = u.role === "BORROWER" || u.role === "GUARANTOR";

  mount(el, html`
    <a class="back" href="#/admin/kyc">KYC queue</a>
    <header class="page-head page-head--row">
      <div><h1>${u.full_name}</h1><p class="lead">${u.role_label}, ${u.email}</p></div>${kycTag(k.status)}
    </header>
    ${k.duplicate_document_users.length ? html`<p class="notice notice--error">This document number was also submitted by ${k.duplicate_document_users.join(", ")}. Check for a duplicate identity before approving.</p>` : ""}
    <div class="columns">
      <section class="panel">
        <h2>Compare with the documents</h2>
        <table class="kv">
          <tr><th scope="row">Document</th><td>${k.document_type_label} <strong>${k.document_number}</strong></td></tr>
          <tr><th scope="row">Legal name</th><td>${k.legal_first_name} ${k.legal_last_name}</td></tr>
          <tr><th scope="row">Name on account</th><td>${u.full_name}</td></tr>
          <tr><th scope="row">Date of birth</th><td>${formatDate(k.date_of_birth)}${p.date_of_birth && p.date_of_birth !== k.date_of_birth ? html` <span class="tag tag--warn">Profile says ${formatDate(p.date_of_birth)}</span>` : ""}</td></tr>
          <tr><th scope="row">Nationality</th><td>${k.nationality}</td></tr>
          <tr><th scope="row">Email</th><td>${u.is_email_verified ? "Verified" : "Not verified"}</td></tr>
          <tr><th scope="row">Phone</th><td>${u.phone_number || "None"} ${u.phone_number ? (u.is_phone_verified ? "(verified)" : "(not verified)") : ""}</td></tr>
          ${incomeRole ? html`
            <tr><th scope="row">Declared income</th><td>${p.monthly_income ? formatMoney(p.monthly_income) + " a month" : "Not declared"}</td></tr>
            <tr><th scope="row">Employment</th><td>${p.employment_status_label || "Not given"}${p.employer_name ? `, ${p.employer_name}` : ""}</td></tr>` : ""}
          <tr><th scope="row">Submitted</th><td>${formatDateTime(k.submitted_at)}</td></tr>
          ${k.reviewed_at ? html`<tr><th scope="row">Reviewed</th><td>${formatDateTime(k.reviewed_at)} by ${k.reviewed_by_email}</td></tr>` : ""}
          ${k.rejection_reason ? html`<tr><th scope="row">Rejection reason</th><td>${k.rejection_reason}</td></tr>` : ""}
          ${k.review_note ? html`<tr><th scope="row">Note</th><td>${k.review_note}</td></tr>` : ""}
        </table>
      </section>
      <section class="panel">
        <h2>Decision</h2>
        ${canDecide ? html`
          <form id="approve-form" class="form" novalidate>
            ${incomeRole ? html`<label class="check"><input type="checkbox" name="income_verified" ${k.files.proof_of_income ? "" : "disabled"}>
              <span>The proof of income confirms the declared income${k.files.proof_of_income ? "" : " (no proof uploaded)"}</span></label>` : ""}
            ${field("note", "Note (optional)", html`<input name="note" maxlength="1000">`)}
            <button class="btn" type="submit">Approve identity</button>
          </form>
          <form id="reject-form" class="form form--danger" novalidate>
            ${field("reason", "Reason for rejecting (the customer sees this)", html`<textarea name="reason" rows="3" maxlength="1000" placeholder="e.g. The photo of the ID is blurred; take a clearer photo in good light."></textarea>`)}
            <button class="btn btn--danger" type="submit">Reject</button>
          </form>`
        : html`<p class="muted">${k.status === "PENDING" ? "Your admin level can view submissions but not decide them." : "This submission has been decided."}</p>`}
      </section>
    </div>
    <section class="panel">
      <h2>Documents</h2>
      ${documentPreviews(k.files)}
    </section>`);

  wireDocuments(el);
  const approve = $("#approve-form", el);
  approve?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await busy(approve.querySelector("button"), "Approving…", () => api.post(`admin/kyc/${k.id}/approve/`, {
        income_verified: Boolean(approve.income_verified?.checked), note: approve.note.value,
      }));
      toast("Identity approved", "ok");
      ctx.navigate("/admin/kyc");
    } catch (err) { toast(err.message, "error"); }
  });
  const reject = $("#reject-form", el);
  reject?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (reject.reason.value.trim().length < 10) {
      reject.querySelector("[data-for=reason]").textContent = "Explain what's wrong in at least 10 characters.";
      return;
    }
    try {
      await busy(reject.querySelector("button"), "Rejecting…", () => api.post(`admin/kyc/${k.id}/reject/`, { reason: reject.reason.value }));
      toast("Submission rejected", "ok");
      ctx.navigate("/admin/kyc");
    } catch (err) {
      if (!showFieldErrors(reject, err)) toast(err.message, "error");
    }
  });
}
