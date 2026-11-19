import { api } from "../api.js";
import { can, PERMISSION_GROUPS, setUser, user } from "../session.js";
import { $, formatDate, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, field, kycTag, loadingBlock, pageHead, showFieldErrors } from "./common.js";

const EMPLOYMENT = [["", "Choose…"], ["EMPLOYED", "Employed"], ["SELF_EMPLOYED", "Self-employed"],
  ["UNEMPLOYED", "Unemployed"], ["STUDENT", "Student"], ["RETIRED", "Retired"]];
const FUNDS = [["", "Choose…"], ["SALARY", "Salary"], ["BUSINESS", "Business income"], ["SAVINGS", "Savings"],
  ["INVESTMENTS", "Other investments"], ["PENSION", "Pension"], ["OTHER", "Other"]];

const options = (list, value) => list.map(([v, l]) => html`<option value="${v}" ${v === (value || "") ? "selected" : ""}>${l}</option>`);
const verifiedTag = (ok) => (ok ? html`<span class="tag tag--ok">Verified</span>` : html`<span class="tag tag--warn">Not verified</span>`);

export async function profileView(el, ctx) {
  const u = user();
  const isCustomer = u.role !== "ADMIN";
  mount(el, html`${pageHead("Profile", "Your details, verification and what your account can do.")}${loadingBlock()}`);
  const details = isCustomer ? await api.get("accounts/me/profile/") : { profile: null };
  const p = details.profile || {};
  const groups = PERMISSION_GROUPS
    .map(([name, labels]) => [name, Object.entries(labels).filter(([perm]) => can(perm)).map(([, label]) => label)])
    .filter(([, items]) => items.length);

  const roleForm = u.role === "INVESTOR" ? html`
      <div class="form__row">
        ${field("occupation", "Occupation", html`<input name="occupation" maxlength="120" value="${p.occupation || ""}">`)}
        ${field("source_of_funds", "Main source of the money you'll invest", html`<select name="source_of_funds">${options(FUNDS, p.source_of_funds)}</select>`)}
      </div>` : html`
      <div class="form__row">
        ${field("employment_status", "Employment", html`<select name="employment_status">${options(EMPLOYMENT, p.employment_status)}</select>`)}
        ${field("employer_name", "Employer or business", html`<input name="employer_name" maxlength="150" value="${p.employer_name || ""}">`)}
      </div>
      <div class="form__row">
        ${field("monthly_income", "Monthly income (KES)", html`<input name="monthly_income" inputmode="decimal" value="${p.monthly_income ?? ""}">`)}
        ${u.role === "BORROWER" ? field("monthly_obligations", "Monthly commitments (KES)",
          html`<input name="monthly_obligations" inputmode="decimal" value="${p.monthly_obligations ?? "0"}">`,
          "Loan repayments, rent and other fixed monthly costs.") : ""}
      </div>
      <p class="small">${p.income_verified
        ? html`<span class="tag tag--ok">Income verified</span> Changing income or employment means it must be verified again.`
        : html`<span class="tag">Income not verified</span> Our team verifies income when they review your identity documents.`}</p>`;

  mount(el, html`
    ${pageHead("Profile", "Your details, verification and what your account can do.")}
    <div class="columns">
      <div class="stack">
        <section class="panel">
          <h2>Contact details</h2>
          <table class="kv">
            <tr><th scope="row">Email</th><td>${u.email} ${verifiedTag(u.is_email_verified)}</td></tr>
            <tr><th scope="row">Phone</th><td>${u.phone_number || "Not added"} ${u.phone_number ? verifiedTag(u.is_phone_verified) : ""}</td></tr>
            ${isCustomer ? html`<tr><th scope="row">Identity</th><td>${kycTag(u.kyc_status)} <a href="#/kyc">Open</a></td></tr>` : ""}
            <tr><th scope="row">Member since</th><td>${formatDate(u.date_joined)}</td></tr>
          </table>
          <div id="verify-email"></div>
          <form id="phone-form" class="form form--inline" novalidate>
            ${field("phone_number", u.phone_number ? "Change phone number" : "Add your phone number",
              html`<input name="phone_number" type="tel" placeholder="0712 345 678" value="">`)}
            <button class="btn btn--quiet" type="submit">${u.phone_number ? "Change number" : "Add number"}</button>
          </form>
          <div id="verify-phone"></div>
        </section>

        <section class="panel">
          <h2>Your name</h2>
          <form id="name-form" class="form" novalidate>
            <div class="form__row">
              ${field("first_name", "First name", html`<input name="first_name" autocomplete="given-name" required value="${u.first_name}">`)}
              ${field("last_name", "Last name", html`<input name="last_name" autocomplete="family-name" required value="${u.last_name}">`)}
            </div>
            <button class="btn" type="submit">Save name</button>
          </form>
        </section>

        ${isCustomer ? html`<section class="panel">
          <h2>About you</h2>
          <p class="panel__text">${u.role === "INVESTOR" ? "Needed to verify where invested money comes from."
            : "Used to check what you can afford and to work out your trust and risk scores."}</p>
          <form id="details-form" class="form" novalidate>
            <div class="form__row">
              ${field("date_of_birth", "Date of birth", html`<input type="date" name="date_of_birth" value="${p.date_of_birth || ""}">`)}
              ${field("county", "County", html`<input name="county" maxlength="60" value="${p.county || ""}">`)}
            </div>
            ${field("town", "Town", html`<input name="town" maxlength="80" value="${p.town || ""}">`)}
            ${roleForm}
            <button class="btn" type="submit">Save details</button>
          </form>
        </section>` : ""}

        <section class="panel">
          <h2>Password</h2>
          <form id="password-form" class="form" novalidate>
            ${field("current_password", "Current password", html`<input type="password" name="current_password" autocomplete="current-password">`)}
            ${field("new_password", "New password", html`<input type="password" name="new_password" autocomplete="new-password">`,
              "At least 10 characters.")}
            <button class="btn btn--quiet" type="submit">Change password</button>
          </form>
        </section>
      </div>

      <section class="panel">
        <h2>What you can do</h2>
        ${groups.map(([name, items]) => html`<h3>${name}</h3><ul class="ticks">${items.map((i) => html`<li>${i}</li>`)}</ul>`)}
        ${u.is_frozen ? html`<p class="notice notice--warn">Some actions are paused while your account is frozen.</p>` : ""}
      </section>
    </div>`);

  const refresh = async (message) => {
    toast(message, "ok");
    await ctx.refreshUser();
    ctx.refreshShell();
  };

  verifyBlock($("#verify-email", el), "EMAIL", u.is_email_verified, u.email, refresh);
  if (u.phone_number) verifyBlock($("#verify-phone", el), "PHONE", u.is_phone_verified, u.phone_number, refresh);

  const phoneForm = $("#phone-form", el);
  phoneForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(phoneForm);
    try {
      await busy(phoneForm.querySelector("button"), "Saving…", () => api.put("auth/phone/", { phone_number: phoneForm.phone_number.value }));
      await refresh("Phone number saved. Verify it with the code we send.");
    } catch (err) {
      if (!showFieldErrors(phoneForm, err)) toast(err.message, "error");
    }
  });

  const nameForm = $("#name-form", el);
  nameForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(nameForm);
    try {
      const updated = await busy(nameForm.querySelector("button"), "Saving…", () => api.patch("accounts/me/", {
        first_name: nameForm.first_name.value.trim(), last_name: nameForm.last_name.value.trim(),
      }));
      setUser(updated);
      toast("Name saved", "ok");
      ctx.refreshShell();
    } catch (err) {
      if (!showFieldErrors(nameForm, err)) toast(err.message, "error");
    }
  });

  const detailsForm = $("#details-form", el);
  detailsForm?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(detailsForm);
    const data = Object.fromEntries(new FormData(detailsForm));
    for (const k of ["date_of_birth", "monthly_income"]) if (data[k] === "") data[k] = null;
    if (data.monthly_obligations === "") data.monthly_obligations = "0";
    try {
      await busy(detailsForm.querySelector("button"), "Saving…", () => api.put("accounts/me/profile/", data));
      toast("Details saved", "ok");
      ctx.rerender();
    } catch (err) {
      if (!showFieldErrors(detailsForm, err)) toast(err.message, "error");
    }
  });

  const pwForm = $("#password-form", el);
  pwForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(pwForm);
    try {
      await busy(pwForm.querySelector("button"), "Changing…", () => api.post("auth/password/change/", {
        current_password: pwForm.current_password.value, new_password: pwForm.new_password.value,
      }));
      pwForm.reset();
      toast("Password changed", "ok");
    } catch (err) {
      if (!showFieldErrors(pwForm, err)) toast(err.message, "error");
    }
  });
}

/** "Send code" + "Enter code" for one channel. */
function verifyBlock(host, channel, verified, destination, onVerified) {
  if (verified) { mount(host, ""); return; }
  const what = channel === "EMAIL" ? "email address" : "phone number";
  mount(host, html`<div class="verify">
    <p class="verify__title">Verify your ${what}</p>
    <p class="small muted">We'll send a 6-digit code to ${destination}. In development the code is printed in the server console.</p>
    <div class="verify__row">
      <button class="btn btn--quiet" type="button" data-send>Send code</button>
      <form class="verify__code" novalidate>
        <input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="Code" aria-label="Verification code">
        <button class="btn" type="submit">Verify</button>
      </form>
    </div>
    <p class="small" data-status role="status"></p>
  </div>`);
  const status = host.querySelector("[data-status]");
  const send = host.querySelector("[data-send]");
  send.addEventListener("click", async () => {
    try {
      const res = await busy(send, "Sending…", () => api.post("auth/otp/request/", { channel }));
      status.textContent = `Code sent to ${res.sent_to}. It expires in ${res.expires_in_minutes} minutes.`;
      host.querySelector("input[name=code]").focus();
    } catch (err) {
      status.textContent = err.message;
    }
  });
  const form = host.querySelector("form");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await busy(form.querySelector("button"), "Checking…", () => api.post("auth/otp/verify/", { channel, code: form.code.value }));
      await onVerified(`${channel === "EMAIL" ? "Email" : "Phone number"} verified`);
    } catch (err) {
      status.textContent = err.fieldError?.("code") || err.message;
    }
  });
}
