// Configuration > Terms & conditions: publish a new version and see who has accepted each one.

import { api } from "../api.js";
import { $, formatDateTime, html, mount, toast } from "../ui.js";
import { busy, clearFieldErrors, errorBlock, field, loadingBlock, pageHead, showFieldErrors } from "./common.js";

export async function adminTermsView(el, ctx) {
  const intro = "Every user must accept the current version before using the platform. Publishing a new version asks everyone to accept it again.";
  mount(el, html`${pageHead("Terms & conditions", intro)}${loadingBlock()}`);
  let versions;
  try {
    versions = await api.get("admin/terms/");
  } catch (err) {
    mount(el, html`${pageHead("Terms & conditions")}${errorBlock(err)}`);
    return;
  }
  const active = versions.find((v) => v.is_active);
  const nextVersion = (versions[0]?.version || 0) + 1;

  mount(el, html`
    ${pageHead("Terms & conditions", intro)}
    <section class="panel" aria-labelledby="publish-title">
      <h2 id="publish-title">Publish a new version</h2>
      <p class="panel__text">Current version: ${active ? `v${active.version}, ${active.accepted_count} accepted so far` : "none published yet, so nobody is asked to accept anything"}.
        Write in plain language. Leave a blank line between paragraphs.</p>
      <form id="terms-publish" class="form" novalidate>
        ${field("title", "Title", html`<input name="title" maxlength="200" value="${active ? active.title : "Terms and conditions"}" required>`)}
        ${field("body", "Text", html`<textarea name="body" rows="16" required></textarea>`, "At least 50 characters.")}
        <p class="form__error" data-error></p>
        <button class="btn" type="submit">Publish version ${nextVersion}</button>
      </form>
    </section>
    <section class="panel" aria-labelledby="versions-title">
      <h2 id="versions-title">Versions</h2>
      <div class="table-wrap"><table class="table">
        <thead><tr><th scope="col">Version</th><th scope="col">Title</th><th scope="col">Published</th><th scope="col">Accepted by</th></tr></thead>
        <tbody>${versions.length ? versions.map((v) => html`<tr>
          <td>v${v.version} ${v.is_active ? html`<span class="tag tag--ok">Current</span>` : ""}</td>
          <td>${v.title}</td>
          <td class="nowrap">${formatDateTime(v.published_at)}</td>
          <td>${v.accepted_count}</td>
        </tr>`) : html`<tr><td colspan="4">No versions yet.</td></tr>`}</tbody>
      </table></div>
    </section>`);

  const form = $("#terms-publish", el);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearFieldErrors(form);
    const err = form.querySelector("[data-error]");
    err.textContent = "";
    try {
      await busy(form.querySelector("button[type=submit]"), "Publishing…", () =>
        api.post("admin/terms/", { title: form.title.value.trim(), body: form.body.value.trim() }));
      toast("Published. Everyone will be asked to accept it.", "ok");
      ctx.rerender();
    } catch (e) {
      if (!showFieldErrors(form, e)) err.textContent = e.message;
    }
  });
}
