import { api } from "../api.js";
import { user } from "../session.js";
import { $, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, field, kycTag, loadingBlock, pageHead, showFieldErrors } from "./common.js";
import { documentLinks, wireDocuments } from "./documents.js";

const FILE_HELP = "JPG, PNG or PDF, up to 5 MB.";

export async function kycView(el, ctx) {
  mount(el, html`${pageHead("Identity verification")}${loadingBlock()}`);
  const data = await api.get("kyc/me/");
  const sub = data.submission;
  const u = user();

  const statusPanel = {
    NOT_SUBMITTED: html`<p>Upload your ID and a selfie. Our team checks them, usually within one working day.
      Until then you can look around, but you can't borrow, invest or guarantee.</p>`,
    PENDING: html`<p>We received your documents on ${formatDateTime(sub?.submitted_at)}. You'll see the result here once our team has reviewed them.</p>`,
    APPROVED: html`<p>Your identity is verified. ${u.role === "BORROWER" ? html`Your trust score is ready: <a href="#/trust">see it</a>.` : ""}</p>`,
    REJECTED: html`<div class="notice notice--error"><p><strong>Your documents couldn't be accepted.</strong></p>
      <p>${sub?.rejection_reason}</p></div><p>Fix the problem described above and submit again.</p>`,
  }[data.status];

  const canSubmit = data.status === "NOT_SUBMITTED" || data.status === "REJECTED";
  mount(el, html`
    ${pageHead("Identity verification", "Required by law before you can borrow, invest or guarantee.")}
    <section class="panel">
      <div class="panel__head"><h2>Status</h2>${kycTag(data.status)}</div>
      ${statusPanel}
      ${sub && !canSubmit ? html`<table class="kv">
        <tr><th scope="row">Document</th><td>${sub.document_type_label} ${sub.document_number}</td></tr>
        <tr><th scope="row">Name on document</th><td>${sub.legal_first_name} ${sub.legal_last_name}</td></tr>
        <tr><th scope="row">Files</th><td>${documentLinks(sub.files)}</td></tr>
      </table>` : ""}
    </section>
    ${canSubmit ? html`<section class="panel">
      <h2>Submit your documents</h2>
      <form id="kyc-form" class="form" novalidate>
        <div class="form__row">
          ${field("document_type", "Document", html`<select name="document_type">
            <option value="NATIONAL_ID">National ID</option><option value="PASSPORT">Passport</option>
            <option value="ALIEN_ID">Alien ID</option></select>`)}
          ${field("document_number", "Document number", html`<input name="document_number" maxlength="20" required>`)}
        </div>
        <div class="form__row">
          ${field("legal_first_name", "First name, as on the document", html`<input name="legal_first_name" value="${u.first_name}" required>`)}
          ${field("legal_last_name", "Last name, as on the document", html`<input name="legal_last_name" value="${u.last_name}" required>`)}
        </div>
        <div class="form__row">
          ${field("date_of_birth", "Date of birth", html`<input type="date" name="date_of_birth" required>`)}
          ${field("nationality", "Nationality", html`<input name="nationality" value="Kenyan">`)}
        </div>
        <div class="form__row">
          ${field("id_front", "Front of the document", html`<input type="file" name="id_front" accept="image/jpeg,image/png,application/pdf" required>`, FILE_HELP)}
          ${field("id_back", "Back of the document (national ID)", html`<input type="file" name="id_back" accept="image/jpeg,image/png,application/pdf">`, FILE_HELP)}
        </div>
        <div class="form__row">
          ${field("selfie", "A selfie holding the document", html`<input type="file" name="selfie" accept="image/jpeg,image/png" capture="user" required>`, "JPG or PNG, up to 5 MB.")}
          ${u.role === "INVESTOR" ? "" : field("proof_of_income", "Proof of income (optional)", html`<input type="file" name="proof_of_income" accept="image/jpeg,image/png,application/pdf">`,
            "A payslip, bank or M-Pesa statement. Lets us verify your income, which improves your score.")}
        </div>
        <p class="small muted">Your documents are stored privately and only our verification team can open them.</p>
        <button class="btn" type="submit">Submit for review</button>
      </form>
    </section>` : ""}`);

  wireDocuments(el);
  const form = $("#kyc-form", el);
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(form);
    const body = new FormData(form);
    for (const name of ["id_back", "proof_of_income"]) {
      const input = form.elements[name];
      if (input && !input.files.length) body.delete(name);
    }
    try {
      await busy(form.querySelector("button[type=submit]"), "Uploading…", () => api.upload("kyc/me/", body));
      toast("Documents submitted", "ok");
      await ctx.refreshUser();
      ctx.refreshShell();
    } catch (err) {
      if (!showFieldErrors(form, err)) toast(err.message, "error");
    }
  });
}
