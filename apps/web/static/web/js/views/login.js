import { login } from "../api.js";
import { $, html, mount } from "../ui.js";

/** Sign-in screen. Calls onSignedIn(user) on success. */
export function loginView(el, { onSignedIn, message } = {}) {
  mount(el, html`
    <div class="auth">
      <section class="auth__story" aria-hidden="true">
        <div class="brand brand--light"><span class="brand__mark"></span><span>P2P Lend</span></div>
        <div class="auth__copy">
          <p class="auth__headline">Repay early.<br>Borrow for less.</p>
          <p class="auth__sub">Every installment you pay on time lowers the rate on your next loan. Investors fund it together; a guarantor stands behind it.</p>
        </div>
        <div class="steps-art">${[1, 2, 3, 4, 5, 6].map((n) => html`<span class="steps-art__bar steps-art__bar--${n}"></span>`)}</div>
      </section>
      <main class="auth__form" id="view" tabindex="-1">
        <form id="login-form" class="form form--auth" novalidate>
          <h1>Sign in</h1>
          <p class="muted">Borrowers, investors, guarantors and administrators all sign in here.</p>
          ${message ? html`<p class="notice" role="status">${message}</p>` : ""}
          <label class="field"><span>Email</span>
            <input type="email" name="email" autocomplete="username" required autofocus>
            <small class="field__error" data-for="email"></small></label>
          <label class="field"><span>Password</span>
            <input type="password" name="password" autocomplete="current-password" required>
            <small class="field__error" data-for="password"></small></label>
          <p class="form__error" id="login-error" role="alert"></p>
          <button class="btn btn--wide" type="submit">Sign in</button>
          <p class="muted center">New to P2P Lend? <a href="#/register">Create an account</a></p>
        </form>
      </main>
    </div>`);

  const form = $("#login-form", el);
  const errorEl = $("#login-error", el);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    form.querySelectorAll(".field__error").forEach((e) => { e.textContent = ""; });
    errorEl.textContent = "";
    const email = form.email.value.trim();
    const password = form.password.value;
    if (!email.includes("@")) { form.querySelector("[data-for=email]").textContent = "Enter the email address you registered with."; return; }
    if (!password) { form.querySelector("[data-for=password]").textContent = "Enter your password."; return; }

    const btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Signing in…";
    try {
      onSignedIn(await login(email, password));
    } catch (err) {
      errorEl.textContent = err.code === "throttled"
        ? "Too many attempts. Wait a minute, then try again."
        : err.message;
      for (const f of ["email", "password"]) {
        const msg = err.fieldError?.(f);
        if (msg) form.querySelector(`[data-for=${f}]`).textContent = msg;
      }
      btn.disabled = false;
      btn.textContent = "Sign in";
      form.password.select();
    }
  });
}
