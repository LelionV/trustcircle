// "Report this person" form, used from the marketplace, chat and loan pages.
import { api } from "../api.js";
import { $, html, mount, toast } from "../ui.js";
import { busy, field } from "./common.js";

const REASONS = [
  ["FRAUD", "Fraud or scam"], ["HARASSMENT", "Harassment or threats"], ["SPAM", "Spam"],
  ["IMPERSONATION", "Pretending to be someone else"], ["OFF_PLATFORM", "Asking to pay or lend outside the platform"],
  ["INAPPROPRIATE", "Offensive or inappropriate"], ["OTHER", "Something else"],
];

/** target: {message_id} | {user_id} | {loan_id} */
export function reportForm(host, target, who = "this person") {
  mount(host, html`<form class="form panel panel--feature" id="report-form" novalidate>
    <h3>Report ${who}</h3>
    <p class="small muted">Our team reviews every report. The person isn't told who reported them.</p>
    ${field("reason", "What's wrong?", html`<select name="reason">${REASONS.map(([v, l]) => html`<option value="${v}">${l}</option>`)}</select>`)}
    ${field("details", "Tell us what happened", html`<textarea name="details" rows="3" maxlength="2000" required></textarea>`, "At least 10 characters.")}
    <p class="form__error" data-error></p>
    <div class="form__actions"><button class="btn btn--danger" type="submit">Send report</button>
      <button class="btn btn--quiet" type="button" data-cancel>Cancel</button></div></form>`);
  const form = $("#report-form", host);
  form.querySelector("[data-cancel]").addEventListener("click", () => { host.innerHTML = ""; });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = form.querySelector("[data-error]");
    err.textContent = "";
    try {
      await busy(form.querySelector("button[type=submit]"), "Sending…", () => api.post("reports/users/", {
        ...target, reason: form.reason.value, details: form.details.value.trim() }));
      host.innerHTML = "";
      toast("Report sent. Thank you.", "ok");
    } catch (e) { err.textContent = e.message; }
  });
}
