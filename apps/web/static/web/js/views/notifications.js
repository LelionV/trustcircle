import { api } from "../api.js";
import { $, $$, formatDateTime, html, mount, toast } from "../ui.js";
import { emptyState, loadingBlock, pageHead } from "./common.js";
import { pager } from "./pager.js";

export async function notificationsView(el, ctx) {
  const page = ctx.query.get("page") || "1";
  const unread = ctx.query.get("unread") === "1";
  mount(el, html`${pageHead("Notifications")}${loadingBlock()}`);
  const data = await api.get("notifications/", { page, unread: unread ? "1" : "" });
  mount(el, html`
    ${pageHead("Notifications", "Payment receipts, reminders, funding and guarantee updates, and messages.")}
    <div class="filters"><label class="check"><input type="checkbox" id="only-unread" ${unread ? "checked" : ""}> Unread only</label>
      <button class="btn btn--quiet btn--small" id="mark-all">Mark all as read</button></div>
    <section class="panel">${data.results.length ? html`<ul class="notes">${data.results.map((n) => html`
      <li class="note ${n.is_read ? "" : "note--unread"}">
        <p class="note__title">${n.link ? html`<a href="${n.link}" data-read="${n.id}">${n.title}</a>` : n.title}</p>
        <p class="note__body">${n.body}</p><p class="note__when">${formatDateTime(n.created_at)}</p></li>`)}</ul>${pager(data, Number(page))}`
      : emptyState("Nothing here", unread ? "You've read everything." : "Notifications will appear here.")}</section>`);
  $("#only-unread", el).addEventListener("change", (ev) => ctx.navigate("/notifications", { unread: ev.target.checked ? "1" : "" }));
  $("#mark-all", el).addEventListener("click", async () => {
    try { await api.post("notifications/read/"); window.dispatchEvent(new Event("p2p:badges")); ctx.rerender(); } catch (e) { toast(e.message, "error"); }
  });
  $$("[data-read]", el).forEach((a) => a.addEventListener("click", () => {
    api.post("notifications/read/", { ids: [Number(a.dataset.read)] }).then(() => window.dispatchEvent(new Event("p2p:badges"))).catch(() => {});
  }));
  $$("[data-page]", el).forEach((b) => b.addEventListener("click", () => ctx.navigate("/notifications", { unread: unread ? "1" : "", page: b.dataset.page })));
}
