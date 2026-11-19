// Chat about loans (borrower ↔ investors, people making offers, guarantor) and with support.
// New messages are fetched every few seconds while a conversation is open.
import { api } from "../api.js";
import { can } from "../session.js";
import { $, $$, formatDateTime, html, mount, toast } from "../ui.js";
import { emptyState, loadingBlock, pageHead } from "./common.js";
import { reportForm } from "./report.js";
import { money } from "./shared.js";

let poller = null;
const stopPolling = () => { if (poller) { clearInterval(poller); poller = null; } };
window.addEventListener("hashchange", stopPolling);

export async function chatListView(el, ctx) {
  stopPolling();
  mount(el, html`${pageHead("Messages")}${loadingBlock()}`);
  const convs = await api.get("chat/");
  mount(el, html`
    ${pageHead("Messages", "Talk to the people on your loans, and agree offers. Never pay or lend outside P2P Lend.")}
    <p><button class="btn btn--quiet" id="support">Message support</button></p>
    <section class="panel">${convs.length ? html`<ul class="convs">${convs.map((c) => html`
      <li><a class="conv ${c.unread ? "conv--unread" : ""}" href="#/chat/${c.id}">
        <span class="conv__title">${c.title}${c.loan ? html` <span class="muted">· ${c.loan.reference}</span>` : ""}</span>
        <span class="conv__last">${c.last_message || "No messages yet"}</span>
        <span class="conv__meta">${c.last_message_at ? formatDateTime(c.last_message_at) : ""}${c.unread ? html` <span class="badge">${c.unread}</span>` : ""}${c.blocked ? " · blocked" : ""}</span></a></li>`)}</ul>`
      : emptyState("No conversations yet", "Start one from a loan in the marketplace, an offer, or a guarantee request.")}</section>`);
  $("#support", el).addEventListener("click", async () => {
    try { const c = await api.post("chat/", { support: true }); ctx.navigate(`/chat/${c.id}`); } catch (e) { toast(e.message, "error"); }
  });
}

function bubble(m) {
  if (m.kind === "SYSTEM" || (m.kind === "OFFER" && !m.sender_id)) {
    return html`<li class="msg msg--system" data-id="${m.id}">
      ${m.offer ? html`<div class="offer-card"><strong>Offer: ${money(m.offer.amount)} at ${m.offer.rate}%</strong> <span class="tag">${m.offer.status_label}</span></div>` : ""}
      <p>${m.body}</p><time>${formatDateTime(m.created_at)}</time></li>`;
  }
  return html`<li class="msg ${m.mine ? "msg--mine" : ""}" data-id="${m.id}">
    ${m.mine ? "" : html`<p class="msg__who">${m.sender}</p>`}
    <p class="msg__body ${m.hidden ? "muted" : ""}">${m.body}</p>
    <time>${formatDateTime(m.created_at)}</time>
    ${!m.mine && !m.hidden && m.sender_id && can("users.report") ? html`<button class="linkish small" data-report="${m.id}">Report</button>` : ""}</li>`;
}

export async function chatView(el, ctx) {
  stopPolling();
  mount(el, html`${pageHead("Conversation")}${loadingBlock()}`);
  const c = await api.get(`chat/${ctx.params.id}/`);
  let lastId = c.messages.length ? c.messages[c.messages.length - 1].id : 0;
  window.dispatchEvent(new Event("p2p:badges"));
  mount(el, html`
    <a class="back" href="#/chat">All messages</a>
    <header class="page-head page-head--row"><div><h1>${c.title}</h1>
      ${c.loan ? html`<p class="lead">About loan ${c.loan.i_am_borrower ? html`<a href="#/loans/${c.loan.id}">${c.loan.reference}</a>` : c.loan.reference} · ${money(c.loan.amount)} · ${c.loan.status_label}</p>` : html`<p class="lead">Our support team usually replies within a working day.</p>`}</div>
      <div>${c.kind === "LOAN" && (!c.blocked || c.blocked_by_me) ? html`<button class="btn btn--quiet btn--small" id="block">${c.blocked ? "Unblock" : "Block"}</button>` : ""}
        ${c.kind === "LOAN" && can("users.report") && c.others.length ? html`<button class="btn btn--quiet btn--small btn--danger-text" id="report-person">Report ${c.others[0].name}</button>` : ""}</div></header>
    <div id="report-host"></div>
    <section class="panel chat">
      <ol class="msgs" id="msgs" aria-live="polite">${c.messages.map(bubble)}</ol>
      ${c.blocked ? html`<p class="notice">This conversation is blocked${c.blocked_by_me ? " by you" : ""}. No new messages can be sent.</p>`
        : html`<form class="chat__form" id="send-form"><label class="sr-only" for="body">Message</label>
          <textarea id="body" name="body" rows="2" maxlength="2000" placeholder="Write a message"></textarea>
          <button class="btn" type="submit">Send</button></form>`}
    </section>`);
  const list = $("#msgs", el);
  const scroll = () => { list.scrollTop = list.scrollHeight; };
  scroll();
  const wireReports = () => $$("[data-report]", el).forEach((b) => {
    b.onclick = () => reportForm($("#report-host", el), { message_id: Number(b.dataset.report) }, "this message");
  });
  wireReports();
  const append = (msgs) => {
    if (!msgs.length) return;
    list.insertAdjacentHTML("beforeend", msgs.map((m) => String(bubble(m))).join(""));
    lastId = msgs[msgs.length - 1].id;
    wireReports();
    scroll();
  };
  poller = setInterval(async () => {
    if (!document.body.contains(list)) { stopPolling(); return; }
    try { const d = await api.get(`chat/${c.id}/`, { after: lastId }); append(d.messages); } catch { /* try again next tick */ }
  }, 4000);

  const form = $("#send-form", el);
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = form.body.value.trim();
    if (!body) return;
    form.querySelector("button").disabled = true;
    try {
      await api.post(`chat/${c.id}/`, { body });
      form.body.value = "";
      const d = await api.get(`chat/${c.id}/`, { after: lastId });
      append(d.messages);
    } catch (e) { toast(e.message, "error"); } finally { form.querySelector("button").disabled = false; form.body.focus(); }
  });
  form?.body.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); } });
  $("#block", el)?.addEventListener("click", async () => {
    if (!c.blocked && !window.confirm("Block this conversation? Neither of you will be able to send messages until you unblock it.")) return;
    try { await api.post(`chat/${c.id}/block/`, { blocked: !c.blocked }); ctx.rerender(); } catch (e) { toast(e.message, "error"); }
  });
  $("#report-person", el)?.addEventListener("click", () => reportForm($("#report-host", el), { user_id: c.others[0].id }, c.others[0].name));
}
