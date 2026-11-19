import { html } from "../ui.js";

const PAGE_SIZE = 20; // matches StandardPagination on the backend

/** Previous/next controls for DRF page-number pagination. Buttons carry data-page. */
export function pager(data, page) {
  const pages = Math.max(1, Math.ceil(data.count / PAGE_SIZE));
  const from = (page - 1) * PAGE_SIZE + 1;
  const to = from + data.results.length - 1;
  return html`<nav class="pager" aria-label="Pages">
    <p class="pager__count">${from}–${to} of ${data.count.toLocaleString("en-KE")}</p>
    ${pages > 1 ? html`<div class="pager__buttons">
      <button class="btn btn--quiet" type="button" data-page="${page - 1}" ${data.previous ? "" : "disabled"}>Previous</button>
      <span class="pager__page">Page ${page} of ${pages}</span>
      <button class="btn btn--quiet" type="button" data-page="${page + 1}" ${data.next ? "" : "disabled"}>Next</button>
    </div>` : ""}
  </nav>`;
}
