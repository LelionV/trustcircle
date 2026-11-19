import { api } from "../api.js";
import { $, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, emptyState, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";
import { statusTag } from "./shared.js";

export async function disputesView(el, ctx) {
  mount(el, html`${pageHead("Disputes")}${loadingBlock()}`);
  const data = await api.get("disputes/");
  mount(el, html`
    ${pageHead("Disputes", "Something wrong with a payment, a repayment, your returns or a fee? Tell us and we'll look into it. Every step is recorded.")}
    <section class="panel"><h2>Raise a dispute</h2>
      <form class="form" id="dispute-form" novalidate>
        <div class="form__row">
          ${field("category", "What's it about?", html`<select name="category">${data.categories.map((c) => html`<option value="${c.value}">${c.label}</option>`)}</select>`)}
          ${field("subject", "Subject", html`<input name="subject" maxlength="120">`)}
        </div>
        ${field("description", "What happened?", html`<textarea name="description" rows="4" maxlength="4000"></textarea>`, "Dates and amounts help us resolve it faster.")}
        <div class="form__row">
          ${field("loan_reference", "Loan reference (optional)", html`<input name="loan_reference" placeholder="LN-…">`)}
          ${field("transaction_reference", "Transaction or M-Pesa code (optional)", html`<input name="transaction_reference">`)}
        </div>
        <p class="form__error" data-error></p>
        <button class="btn" type="submit">Send</button>
      </form></section>
    <section class="panel"><h2>Your disputes</h2>
      ${data.disputes.length ? html`<table class="table table--plain"><thead><tr><th scope="col">Reference</th><th scope="col">Subject</th><th scope="col">Status</th><th scope="col">Outcome</th><th scope="col">Updated</th></tr></thead>
        <tbody>${data.disputes.map((d) => html`<tr><td>${d.reference}</td><td>${d.subject}<span class="sub">${d.category_label}</span></td>
          <td>${statusTag(d.status, d.status_label)}</td><td class="small">${d.resolution}</td><td class="nowrap">${formatDateTime(d.updated_at)}</td></tr>`)}</tbody></table>`
      : emptyState("No disputes", "We hope it stays that way.")}</section>`);
  const form = $("#dispute-form", el);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(form);
    const err = form.querySelector("[data-error]");
    err.textContent = "";
    try {
      const d = await busy(form.querySelector("button"), "Sending…", () => api.post("disputes/", Object.fromEntries(new FormData(form))));
      toast(`Dispute ${d.reference} raised`, "ok");
      ctx.rerender();
    } catch (e) { if (!showFieldErrors(form, e)) err.textContent = e.message; }
  });
}
