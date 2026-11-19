import { can } from "../session.js";
import { $, html, mount } from "../ui.js";
import { field, pageHead } from "./common.js";
import { download } from "./shared.js";

export function statementsView(el) {
  mount(el, html`
    ${pageHead("Statements", "Download your records as spreadsheets (CSV opens in Excel or Google Sheets).")}
    <section class="panel"><h2>Wallet statement</h2>
      <p class="panel__text">Every movement on your wallet: deposits, withdrawals, investments, repayments, fees and locks, with the balance after each.</p>
      <form class="form form--inline" id="stmt-form">
        ${field("start", "From", html`<input type="date" name="start">`)}${field("end", "To", html`<input type="date" name="end">`)}
        <button class="btn" type="submit">Download</button></form></section>
    ${can("investments.view_own") ? html`<section class="panel"><h2>Returns statement</h2>
      <p class="panel__text">Every repayment and recovery you've received from loans you funded, split into principal and interest.</p>
      <button class="btn" id="returns">Download</button></section>` : ""}`);
  $("#stmt-form", el).addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.currentTarget;
    const qs = new URLSearchParams(Object.entries({ start: f.start.value, end: f.end.value }).filter(([, v]) => v));
    download(`/api/v1/wallet/statement.csv${[...qs].length ? `?${qs}` : ""}`, "p2plend-statement.csv");
  });
  $("#returns", el)?.addEventListener("click", () => download("/api/v1/investments/statement.csv", "p2plend-returns.csv"));
}
