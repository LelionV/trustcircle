import { api } from "../api.js";
import { can, user } from "../session.js";
import { $, $$, formatDate, formatDateTime, formatMoney, html, icon, mount, toast } from "../ui.js";
import { emptyState, errorBlock, field, kycTag, loadingBlock, pageHead, riskTag } from "./common.js";
import { closeDrawer, openDrawer } from "./drawer.js";
import { pager } from "./pager.js";

const ROLES = [["", "All roles"], ["BORROWER", "Borrowers"], ["INVESTOR", "Investors"], ["GUARANTOR", "Guarantors"], ["ADMIN", "Administrators"]];
const STATUSES = [["", "Any status"], ["active", "Active"], ["frozen", "Frozen"], ["inactive", "Deactivated"]];

function statusTag(u) {
  if (!u.is_active) return html`<span class="tag">Deactivated</span>`;
  if (u.is_frozen) return html`<span class="tag tag--warn">${icon("snow", "icon icon--xs")}Frozen</span>`;
  return html`<span class="tag tag--ok">Active</span>`;
}

export async function usersView(el, ctx) {
  const q = { search: ctx.query.get("search") || "", role: ctx.query.get("role") || "", status: ctx.query.get("status") || "", page: ctx.query.get("page") || "1" };
  const options = (list, value) => list.map(([v, label]) => html`<option value="${v}" ${v === value ? "selected" : ""}>${label}</option>`);

  mount(el, html`
    ${pageHead("Users", "Look up borrowers, investors, guarantors and administrators.")}
    <form class="filters" id="user-filters" role="search">
      <label class="field field--search"><span class="sr-only">Search</span>
        ${icon("search", "icon icon--sm")}
        <input type="search" name="search" placeholder="Name, email or phone" value="${q.search}"></label>
      <label class="field"><span class="sr-only">Role</span><select name="role">${options(ROLES, q.role)}</select></label>
      <label class="field"><span class="sr-only">Status</span><select name="status">${options(STATUSES, q.status)}</select></label>
      <button class="btn btn--quiet" type="submit">Search</button>
    </form>
    <div id="user-results">${loadingBlock()}</div>`);

  const form = $("#user-filters", el);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    ctx.navigate("/admin/users", { search: form.search.value.trim(), role: form.role.value, status: form.status.value });
  });
  $$("select", form).forEach((s) => s.addEventListener("change", () => form.requestSubmit()));

  const host = $("#user-results", el);
  let data;
  try {
    data = await api.get("admin/users/", q);
  } catch (err) {
    mount(host, errorBlock(err));
    return;
  }
  if (!data.results.length) {
    mount(host, emptyState("No users match", "Try a different name, or clear the role and status filters.", { href: "#/admin/users", label: "Clear filters" }));
    return;
  }
  mount(host, html`
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Verified</th><th scope="col">Joined</th></tr></thead>
        <tbody>${data.results.map((u) => html`<tr>
          <td><button class="linkish" type="button" data-user="${u.id}">${u.full_name}</button><span class="sub">${u.email}</span></td>
          <td>${u.role_label}${u.role === "ADMIN" ? html`<span class="sub">${u.admin_level_label.split(" (")[0]}</span>` : ""}</td>
          <td>${statusTag(u)}</td>
          <td>${[u.is_email_verified && "Email", u.is_phone_verified && "Phone"].filter(Boolean).join(", ") || html`<span class="muted">None</span>`}</td>
          <td>${formatDate(u.date_joined)}</td>
        </tr>`)}</tbody>
      </table>
    </div>
    ${pager(data, Number(q.page))}`);

  const byId = new Map(data.results.map((u) => [u.id, u]));
  $$("[data-user]", host).forEach((b) => b.addEventListener("click", () => showUser(byId.get(b.dataset.user), ctx)));
  $$("[data-page]", host).forEach((b) => b.addEventListener("click", () => ctx.navigate("/admin/users", { ...q, page: b.dataset.page })));
}

function showUser(u, ctx) {
  const me = user();
  const isSelf = u.id === me.id;
  const canFreeze = can("admin.accounts.freeze") && !isSelf && (u.role !== "ADMIN" || can("admin.users.manage"));
  const freezeNote = isSelf
    ? "You can't freeze your own account."
    : u.role === "ADMIN" && !can("admin.users.manage")
      ? "Only a super administrator can freeze another administrator."
      : !can("admin.accounts.freeze") ? "Your admin level can't freeze accounts." : "";

  const panel = openDrawer(html`
    <h2 id="drawer-title">${u.full_name}</h2>
    <p class="muted">${u.email}</p>
    <table class="kv">
      <tr><th scope="row">Role</th><td>${u.role_label}${u.role === "ADMIN" ? `, ${u.admin_level_label}` : ""}</td></tr>
      <tr><th scope="row">Status</th><td>${statusTag(u)}</td></tr>
      <tr><th scope="row">Phone</th><td>${u.phone_number || "Not added"}</td></tr>
      <tr><th scope="row">Email verified</th><td>${u.is_email_verified ? "Yes" : "No"}</td></tr>
      <tr><th scope="row">Phone verified</th><td>${u.is_phone_verified ? "Yes" : "No"}</td></tr>
      <tr><th scope="row">Joined</th><td>${formatDate(u.date_joined)}</td></tr>
      <tr><th scope="row">Last sign-in</th><td>${formatDateTime(u.last_login)}</td></tr>
    </table>
    ${canFreeze ? html`
      <form class="form form--danger" id="freeze-form" novalidate>
        <h3>${u.is_frozen ? "Unfreeze this account" : "Freeze this account"}</h3>
        <p class="small">${u.is_frozen
          ? "Withdrawals, transfers, new investments, applications and guarantees will work again."
          : "Withdrawals, transfers, new investments, applications and guarantees stop until the account is unfrozen. Repayments still go through."}</p>
        <label class="field"><span>Reason (kept in the audit trail)</span>
          <textarea name="reason" rows="3" minlength="10" maxlength="1000" required></textarea>
          <small class="field__error" data-for="reason"></small></label>
        <button class="btn ${u.is_frozen ? "" : "btn--danger"}" type="submit">${u.is_frozen ? "Unfreeze account" : "Freeze account"}</button>
      </form>` : freezeNote ? html`<p class="notice">${freezeNote}</p>` : ""}
    <div id="user-extra">${loadingBlock("Loading identity, trust and risk")}</div>
    ${can("admin.audit.view") ? html`<a class="btn btn--quiet" href="#/admin/audit?entity_id=${u.id}">See this user's audit history</a>` : ""}
  `);
  loadExtra(panel, u, ctx);

  const form = $("#freeze-form", panel);
  form?.reason.addEventListener("input", () => { form.querySelector("[data-for=reason]").textContent = ""; });
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const reason = form.reason.value.trim();
    const err = form.querySelector("[data-for=reason]");
    if (reason.length < 10) { err.textContent = "Give a reason of at least 10 characters."; return; }
    err.textContent = "";
    const btn = form.querySelector("button");
    btn.disabled = true;
    try {
      const updated = await api.post(`admin/users/${u.id}/${u.is_frozen ? "unfreeze" : "freeze"}/`, { reason });
      toast(updated.is_frozen ? "Account frozen" : "Account unfrozen", "ok");
      closeDrawer();
      ctx.rerender();
    } catch (e) {
      err.textContent = e.fieldError?.("reason") || e.message;
      btn.disabled = false;
    }
  });
}


const LEVELS = [["SUPPORT", "Support"], ["OPERATIONS", "Operations"], ["FINANCE", "Finance"], ["SUPER", "Super"]];
const ROLE_CHOICES = [["BORROWER", "Borrower"], ["INVESTOR", "Investor"], ["GUARANTOR", "Guarantor"], ["ADMIN", "Administrator"]];
const RISK_CLASSES = [["", "Use the calculated rating"], ["VERY_LOW", "Very low"], ["LOW", "Low"], ["MEDIUM", "Medium"], ["HIGH", "High"], ["CRITICAL", "Critical"]];

async function loadExtra(panel, u, ctx) {
  const host = $("#user-extra", panel);
  let d;
  try {
    d = await api.get(`admin/users/${u.id}/`);
  } catch (err) {
    mount(host, html`<p class="notice notice--error">${err.message}</p>`);
    return;
  }
  const me = user();
  const isSelf = u.id === me.id;
  const t = d.trust;
  const r = d.risk || {};
  const p = d.profile;
  mount(host, html`
    ${u.role !== "ADMIN" ? html`<h3>Standing</h3>
    <table class="kv">
      <tr><th scope="row">Identity</th><td>${kycTag(d.kyc_status)}</td></tr>
      ${t ? html`<tr><th scope="row">Trust score</th><td>${t.is_scored ? html`<strong>${t.score}</strong> ${t.bracket ? `(${t.bracket.label})` : ""}` : html`<span class="muted">Not scored</span>`}</td></tr>` : ""}
      <tr><th scope="row">Risk</th><td>${r.is_assessed ? html`${riskTag(r.classification)} score ${r.score}${r.is_overridden ? html` <span class="tag tag--warn">Overridden</span>` : ""}` : html`<span class="muted">Not assessed</span>`}</td></tr>
      ${p && p.monthly_income !== undefined ? html`<tr><th scope="row">Income</th><td>${p.monthly_income ? formatMoney(p.monthly_income) : "Not declared"} ${p.income_verified ? html`<span class="tag tag--ok">Verified</span>` : ""}</td></tr>` : ""}
      ${p && p.county ? html`<tr><th scope="row">Location</th><td>${[p.town, p.county].filter(Boolean).join(", ")}</td></tr>` : ""}
    </table>` : ""}
    ${t && t.is_scored && can("admin.trust.override") && !isSelf ? html`
      <form class="form form--tool" id="trust-form" novalidate>
        <h3>Adjust trust score</h3>
        <p class="small muted">Adds or removes points on top of the calculated score. Recorded with your name and reason; the borrower sees the change in their history.</p>
        <div class="form__row">
          ${field("points", "Points (e.g. 5 or -5)", html`<input name="points" inputmode="numeric">`)}
          ${field("reason", "Reason", html`<input name="reason" maxlength="1000">`)}
        </div>
        <button class="btn btn--quiet" type="submit">Apply adjustment</button>
      </form>` : ""}
    ${r.is_assessed && can("admin.risk.override") && !isSelf ? html`
      <form class="form form--tool" id="risk-form" novalidate>
        <h3>Risk rating override</h3>
        <div class="form__row">
          ${field("classification", "Rating", html`<select name="classification">${RISK_CLASSES.map(([v, l]) => html`<option value="${v}" ${v === (r.is_overridden ? r.classification : "") ? "selected" : ""}>${l}</option>`)}</select>`)}
          ${field("reason", "Reason", html`<input name="reason" maxlength="1000">`)}
        </div>
        <button class="btn btn--quiet" type="submit">Save rating</button>
      </form>` : ""}
    ${can("admin.roles.manage") && !isSelf ? html`
      <form class="form form--tool" id="role-form" novalidate>
        <h3>Role</h3>
        <div class="form__row">
          ${field("role", "Role", html`<select name="role">${ROLE_CHOICES.map(([v, l]) => html`<option value="${v}" ${v === u.role ? "selected" : ""}>${l}</option>`)}</select>`)}
          ${field("admin_level", "Admin level", html`<select name="admin_level"><option value="NONE">None</option>${LEVELS.map(([v, l]) => html`<option value="${v}" ${v === u.admin_level ? "selected" : ""}>${l}</option>`)}</select>`)}
        </div>
        ${field("reason", "Reason", html`<input name="reason" maxlength="1000">`)}
        <button class="btn btn--quiet" type="submit">Change role</button>
      </form>` : ""}`);

  const wire = (id, path, build, message) => {
    const form = $(`#${id}`, host);
    form?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      form.querySelectorAll(".field__error").forEach((e) => { e.textContent = ""; });
      const body = build(form);
      if (!body.reason || body.reason.length < 10) {
        form.querySelector("[data-for=reason]").textContent = "Give a reason of at least 10 characters.";
        return;
      }
      const btn = form.querySelector("button");
      btn.disabled = true;
      try {
        await api.post(path, body);
        toast(message, "ok");
        closeDrawer();
        ctx.rerender();
      } catch (err) {
        let shown = false;
        form.querySelectorAll(".field__error").forEach((slot) => {
          const msg = err.fieldError?.(slot.dataset.for);
          if (msg) { slot.textContent = msg; shown = true; }
        });
        if (!shown) toast(err.message, "error");
        btn.disabled = false;
      }
    });
  };
  wire("trust-form", `admin/users/${u.id}/trust/adjust/`,
    (f) => ({ points: Number.parseInt(f.points.value, 10), reason: f.reason.value.trim() }), "Trust score adjusted");
  wire("risk-form", `admin/users/${u.id}/risk/override/`,
    (f) => ({ classification: f.classification.value, reason: f.reason.value.trim() }), "Risk rating saved");
  wire("role-form", `admin/users/${u.id}/role/`,
    (f) => ({ role: f.role.value, admin_level: f.role.value === "ADMIN" ? f.admin_level.value : "NONE", reason: f.reason.value.trim() }),
    "Role changed");
}
