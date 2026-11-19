import { register } from "../api.js";
import { $, html, mount } from "../ui.js";

const ROLES = [
  ["BORROWER", "Borrow money", "Apply for a loan funded by investors. Your rate improves as you repay on time."],
  ["INVESTOR", "Invest in loans", "Fund all or part of a loan and earn interest as it is repaid."],
  ["GUARANTOR", "Guarantee loans", "Stand behind someone's loan and earn a commission from its interest."],
];

export function registerView(el, { onSignedIn }) {
  mount(el, html`
    <div class="auth">
      <section class="auth__story" aria-hidden="true">
        <div class="brand brand--light"><span class="brand__mark"></span><span>P2P Lend</span></div>
        <div class="auth__copy">
          <p class="auth__headline">Repay early.<br>Borrow for less.</p>
          <p class="auth__sub">One account to borrow, invest or guarantee. You'll verify your email, phone and identity after signing up.</p>
        </div>
        <div class="steps-art">${[1, 2, 3, 4, 5, 6].map((n) => html`<span class="steps-art__bar steps-art__bar--${n}"></span>`)}</div>
      </section>
      <main class="auth__form" id="view" tabindex="-1">
        <form id="register-form" class="form form--auth" novalidate>
          <h1>Create your account</h1>
          <fieldset class="choices">
            <legend>I want to</legend>
            ${ROLES.map(([value, title, text], i) => html`<label class="choice choice--tall">
              <input type="radio" name="role" value="${value}" ${i === 0 ? "checked" : ""}>
              <span><strong>${title}</strong><small>${text}</small></span>
            </label>`)}
          </fieldset>
          <div class="form__row">
            <label class="field"><span>First name</span><input name="first_name" autocomplete="given-name" required>
              <small class="field__error" data-for="first_name"></small></label>
            <label class="field"><span>Last name</span><input name="last_name" autocomplete="family-name" required>
              <small class="field__error" data-for="last_name"></small></label>
          </div>
          <label class="field"><span>Email</span><input type="email" name="email" autocomplete="email" required>
            <small class="field__error" data-for="email"></small></label>
          <label class="field"><span>Phone number (optional now, needed before borrowing)</span>
            <input type="tel" name="phone_number" autocomplete="tel" placeholder="0712 345 678">
            <small class="field__error" data-for="phone_number"></small></label>
          <label class="field"><span>Password</span><input type="password" name="password" autocomplete="new-password" required>
            <small class="field__help">At least 10 characters. Avoid common words and all-number passwords.</small>
            <small class="field__error" data-for="password"></small></label>
          <p class="form__error" id="register-error" role="alert"></p>
          <button class="btn btn--wide" type="submit">Create account</button>
          <p class="muted center">Already registered? <a href="#/login">Sign in</a></p>
        </form>
      </main>
    </div>`);

  const form = $("#register-form", el);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    form.querySelectorAll(".field__error").forEach((e) => { e.textContent = ""; });
    $("#register-error", el).textContent = "";
    const data = Object.fromEntries(new FormData(form));
    let missing = false;
    for (const f of ["first_name", "last_name", "email", "password"]) {
      if (!String(data[f] || "").trim()) {
        form.querySelector(`[data-for=${f}]`).textContent = "This is required.";
        missing = true;
      }
    }
    if (missing) return;
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Creating your account…";
    try {
      onSignedIn(await register(data));
    } catch (err) {
      let shown = false;
      for (const f of ["first_name", "last_name", "email", "phone_number", "password", "role"]) {
        const msg = err.fieldError?.(f);
        const slot = form.querySelector(`[data-for=${f}]`);
        if (msg && slot) { slot.textContent = msg; shown = true; }
      }
      if (!shown) $("#register-error", el).textContent = err.message;
      btn.disabled = false;
      btn.textContent = "Create account";
    }
  });
}
