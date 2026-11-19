// Configuration > Payments & SMS: wallet providers (IntaSend, Pesapal, Paystack) and the TalkSasa SMS account.
// Secrets are write-only: the screen shows whether they are saved, never the values.

import { api } from "../api.js";
import { $, $$, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, errorBlock, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";

const ENVIRONMENTS = { SANDBOX: "Test (sandbox)", LIVE: "Live" };
const onOff = (on) => (on ? html`<span class="tag tag--ok">On</span>` : html`<span class="tag">Off</span>`);
const yesNo = (value) => html`<select name="is_enabled">
  <option value="true" ${value ? "selected" : ""}>On</option>
  <option value="false" ${value ? "" : "selected"}>Off</option>
</select>`;

export async function adminIntegrationsView(el, ctx) {
  mount(el, html`${pageHead("Payments & SMS", "Connect the providers members pay through and the SMS account. Keys are stored encrypted and never shown again.")}${loadingBlock()}`);
  let data;
  try {
    data = await api.get("admin/integrations/");
  } catch (err) {
    mount(el, html`${pageHead("Payments & SMS")}${errorBlock(err)}`);
    return;
  }

  mount(el, html`
    ${pageHead("Payments & SMS", "Connect the providers members pay through and the SMS account. Keys are stored encrypted and never shown again.")}
    <div class="stack">
      ${data.gateways.map(gatewayPanel)}
      ${smsPanel(data.sms)}
    </div>`);

  $$("[data-gateway-form]", el).forEach((form) => form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = {
      is_enabled: form.is_enabled.value === "true",
      environment: form.environment.value,
      public_key: form.public_key.value.trim(),
      callback_base_url: form.callback_base_url.value.trim(),
    };
    if (form.secret_key.value.trim()) body.secret_key = form.secret_key.value.trim();
    if (form.webhook_secret && form.webhook_secret.value.trim()) body.webhook_secret = form.webhook_secret.value.trim();
    save(form, `admin/integrations/gateways/${form.dataset.gatewayForm}/`, body, ctx);
  }));

  const smsForm = $("#sms-form", el);
  smsForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = {
      is_enabled: smsForm.is_enabled.value === "true",
      sender_id: smsForm.sender_id.value.trim(),
      base_url: smsForm.base_url.value.trim(),
    };
    if (smsForm.api_key.value.trim()) body.api_key = smsForm.api_key.value.trim();
    save(smsForm, "admin/integrations/sms/", body, ctx);
  });

  const testForm = $("#sms-test-form", el);
  testForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = testForm.querySelector("[data-error]");
    err.textContent = "";
    const phones = testForm.phones.value.split(/[\s,]+/).map((p) => p.trim()).filter(Boolean);
    try {
      const result = await busy(testForm.querySelector("button[type=submit]"), "Sending…", () =>
        api.post("admin/integrations/sms/test/", { phones, message: testForm.message.value.trim() }));
      const failed = result.failed.length;
      toast(`Sent ${result.sent}. ${failed} failed${failed ? `: ${result.failed[0].error}` : ""}.`, failed ? "info" : "ok");
    } catch (e) {
      err.textContent = e.message;
    }
  });
}

async function save(form, path, body, ctx) {
  clearFieldErrors(form);
  const err = form.querySelector("[data-error]");
  err.textContent = "";
  try {
    await busy(form.querySelector("button[type=submit]"), "Saving…", () => api.put(path, body));
    toast("Saved", "ok");
    ctx.rerender();
  } catch (e) {
    if (!showFieldErrors(form, e)) err.textContent = e.message;
  }
}

function gatewayPanel(g) {
  const missing = g.problems.length && g.is_enabled ? html`<p class="notice">Still missing: ${g.problems.join(", ")}.</p>` : "";
  return html`<section class="panel" aria-labelledby="gw-${g.code}">
    <h2 id="gw-${g.code}">${g.label} ${onOff(g.is_enabled)}</h2>
    <p class="panel__text">${g.note}</p>
    ${missing}
    <form class="form" data-gateway-form="${g.code}" novalidate>
      <div class="form__row">
        ${field("is_enabled", "Members can pay with it", yesNo(g.is_enabled))}
        ${field("environment", "Environment", html`<select name="environment">${Object.entries(ENVIRONMENTS).map(([k, l]) =>
          html`<option value="${k}" ${k === g.environment ? "selected" : ""}>${l}</option>`)}</select>`,
        "Use Test while you check the setup. Money is only real on Live.")}
      </div>
      <div class="form__row">
        ${field("public_key", g.code === "PESAPAL" ? "Consumer key" : "Publishable key (optional)",
          html`<input name="public_key" value="${g.public_key}" autocomplete="off">`)}
        ${field("callback_base_url", "Public address of this server", html`<input name="callback_base_url" value="${g.callback_base_url}" placeholder="https://p2p.example.co.ke">`,
          "The address members' browsers and the provider use to reach this server. No trailing slash.")}
      </div>
      ${field("secret_key", g.code === "PESAPAL" ? "Consumer secret" : "Secret key",
        html`<input name="secret_key" type="password" autocomplete="new-password" placeholder="${g.secret_set ? "Saved. Leave blank to keep it." : "Paste the secret key"}">`)}
      ${g.code === "INTASEND" ? field("webhook_secret", "Webhook challenge",
        html`<input name="webhook_secret" type="password" autocomplete="new-password" placeholder="${g.webhook_secret_set ? "Saved. Leave blank to keep it." : "Choose a challenge text"}">`,
        "Enter the same text in IntaSend's webhook settings. Every callback must include it.") : ""}
      ${g.webhook_url ? html`<p class="small">Callback address to register with ${g.label}: <code>${g.webhook_url}</code></p>` : ""}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save ${g.label}</button>
    </form>
  </section>`;
}

function smsPanel(s) {
  return html`<section class="panel" aria-labelledby="sms-title">
    <h2 id="sms-title">SMS through TalkSasa ${onOff(s.is_enabled)}</h2>
    <p class="panel__text">Used for verification codes and account messages. Use the API key from your TalkSasa account and a sender ID TalkSasa has approved.</p>
    <form id="sms-form" class="form" novalidate>
      <div class="form__row">
        ${field("is_enabled", "Send SMS through TalkSasa", yesNo(s.is_enabled))}
        ${field("sender_id", "Sender ID", html`<input name="sender_id" maxlength="11" value="${s.sender_id}">`,
          "Up to 11 letters or numbers.")}
      </div>
      ${field("base_url", "API address", html`<input name="base_url" value="${s.base_url}">`,
        "Use the address in your TalkSasa API documentation.")}
      ${field("api_key", "API key", html`<input name="api_key" type="password" autocomplete="new-password" placeholder="${s.api_key_set ? "Saved. Leave blank to keep it." : "Paste the API key"}">`)}
      <p class="form__error" data-error></p>
      <button class="btn" type="submit">Save SMS settings</button>
    </form>
    <h3>Send a test</h3>
    <form id="sms-test-form" class="form" novalidate>
      ${field("phones", "Numbers", html`<textarea name="phones" rows="2" placeholder="+254712345678, +254700000000"></textarea>`,
        "Up to 50 numbers, separated by commas or new lines. Each message uses your TalkSasa credits.")}
      ${field("message", "Message", html`<textarea name="message" rows="2" maxlength="480">P2P Lend test message. You can ignore this.</textarea>`)}
      <p class="form__error" data-error></p>
      <button class="btn btn--quiet" type="submit">Send test</button>
    </form>
  </section>`;
}
