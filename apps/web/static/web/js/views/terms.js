// Terms and conditions: every user accepts the current version before using the app.

import { api } from "../api.js";
import { $, html, mount } from "../ui.js";
import { busy, errorBlock, loadingBlock } from "./common.js";

export async function termsView(el, { onAccepted, onSignOut }) {
  mount(el, html`<div class="terms-page">
    <header class="topbar"><div class="brand"><span class="brand__mark"></span><span>P2P Lend</span></div></header>
    <main class="terms" id="terms-main" tabindex="-1">${loadingBlock("Loading the terms")}</main>
  </div>`);
  const main = $("#terms-main", el);

  let current;
  try {
    current = await api.get("legal/current/");
  } catch (err) {
    mount(main, errorBlock(err));
    return;
  }
  if (!current.terms || current.accepted) {
    onAccepted();
    return;
  }

  const t = current.terms;
  const paragraphs = t.body.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  mount(main, html`<article class="panel terms__panel">
    <p class="eyebrow">Version ${t.version}</p>
    <h1>${t.title}</h1>
    <div class="terms__body">${paragraphs.map((p) => html`<p>${p}</p>`)}</div>
    <form id="terms-form" class="form" novalidate>
      <label class="checkbox"><input type="checkbox" name="agree"> <span>I have read these terms and conditions and I agree to them.</span></label>
      <p class="form__error" data-error></p>
      <div class="form__actions">
        <button class="btn btn--quiet" type="button" id="terms-sign-out">Sign out</button>
        <button class="btn" type="submit">Accept and continue</button>
      </div>
    </form>
  </article>`);

  $("#terms-sign-out", main).addEventListener("click", onSignOut);
  $("#terms-form", main).addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const err = $("[data-error]", form);
    err.textContent = "";
    if (!form.agree.checked) {
      err.textContent = "Tick the box to show you have read and agree to the terms.";
      return;
    }
    try {
      await busy(form.querySelector("button[type=submit]"), "Saving…", () => api.post("legal/accept/"));
      onAccepted();
    } catch (e) {
      err.textContent = e.message;
    }
  });
}
