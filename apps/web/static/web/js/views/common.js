import { html, icon } from "../ui.js";

const ACTION_NAMES = {
  "user.account.frozen": "Account frozen",
  "user.account.unfrozen": "Account unfrozen",
  "user.profile.updated": "Profile updated",
};

export const actionName = (action) => ACTION_NAMES[action] || action;

export function pageHead(title, lead) {
  return html`<header class="page-head"><h1>${title}</h1>${lead ? html`<p class="lead">${lead}</p>` : ""}</header>`;
}

/** Ordered steps. state: "done" | "todo" | "later" */
export function checklist(steps) {
  const label = { done: "Done", todo: "To do", later: "Not open yet" };
  return html`<ol class="steps">
    ${steps.map((s) => html`<li class="step step--${s.state}">
      <span class="step__mark" aria-hidden="true">${s.state === "done" ? icon("check", "icon icon--sm") : ""}</span>
      <div class="step__body">
        <p class="step__title">${s.title}</p>
        <p class="step__detail">${s.detail}</p>
      </div>
      <span class="step__state">${label[s.state]}</span>
    </li>`)}
  </ol>`;
}

export function emptyState(title, body, action) {
  return html`<div class="empty">
    <p class="empty__title">${title}</p>
    <p class="empty__body">${body}</p>
    ${action ? html`<a class="btn btn--quiet" href="${action.href}">${action.label}</a>` : ""}
  </div>`;
}

export function errorBlock(err, retryId) {
  return html`<div class="notice notice--error" role="alert">
    <p>${err.message}</p>
    ${err.requestId ? html`<p class="muted small">Reference ${err.requestId}</p>` : ""}
    ${retryId ? html`<button class="btn btn--quiet" type="button" id="${retryId}">Try again</button>` : ""}
  </div>`;
}

export const loadingBlock = (text = "Loading") => html`<p class="loading" role="status">${text}…</p>`;

// --- Shared helpers for phases 2–4 ----------------------------------------------

const MORE_ACTIONS = {
  "user.registered": "Account created",
  "user.email.verified": "Email verified",
  "user.phone.verified": "Phone verified",
  "user.phone.changed": "Phone number changed",
  "user.password.changed": "Password changed",
  "user.profile.details_updated": "Profile details updated",
  "user.role.changed": "Role changed",
  "kyc.submitted": "Identity documents submitted",
  "kyc.approved": "Identity verified",
  "kyc.rejected": "Identity documents rejected",
  "trust.adjusted": "Trust score adjusted",
  "risk.override.set": "Risk rating overridden",
  "risk.override.cleared": "Risk override removed",
  "config.brackets.published": "Interest brackets changed",
  "config.trust.published": "Trust scoring rules changed",
  "config.risk.published": "Risk rules changed",
  "config.product.saved": "Loan product saved",
  "loan.draft_created": "Loan application started",
  "loan.submitted": "Loan application submitted",
  "loan.under_review": "Loan review started",
  "loan.approved": "Loan approved",
  "loan.rejected": "Loan rejected",
  "loan.published": "Loan opened for funding",
  "loan.cancelled": "Loan cancelled",
  "loan.document_added": "Loan document added",
};
Object.assign(ACTION_NAMES, MORE_ACTIONS);

const LOAN_TONES = {
  DRAFT: "", SUBMITTED: "info", UNDER_REVIEW: "info", APPROVED: "ok", PUBLISHED: "ok", PARTIALLY_FUNDED: "ok",
  FULLY_FUNDED: "ok", REJECTED: "bad", CANCELLED: "", ACTIVE: "ok", OVERDUE: "warn", DEFAULTED: "bad", COMPLETED: "ok",
};

export const loanTag = (status, label) => html`<span class="tag ${LOAN_TONES[status] ? `tag--${LOAN_TONES[status]}` : ""}">${label}</span>`;

const KYC = {
  NOT_SUBMITTED: ["Not submitted", ""], PENDING: ["Waiting for review", "info"],
  APPROVED: ["Verified", "ok"], REJECTED: ["Rejected", "bad"],
};
export const kycTag = (status) => {
  const [label, tone] = KYC[status] || [status, ""];
  return html`<span class="tag ${tone ? `tag--${tone}` : ""}">${label}</span>`;
};

const RISK_TONES = { VERY_LOW: "ok", LOW: "ok", MEDIUM: "info", HIGH: "warn", CRITICAL: "bad" };
const RISK_LABELS = { VERY_LOW: "Very low", LOW: "Low", MEDIUM: "Medium", HIGH: "High", CRITICAL: "Critical" };
export const riskTag = (cls) => (cls
  ? html`<span class="tag tag--${RISK_TONES[cls] || "info"}">${RISK_LABELS[cls] || cls} risk</span>`
  : html`<span class="muted">Not assessed</span>`);

export const CONFIDENCE = { NEW: "New borrower", LOW: "Low", MEDIUM: "Medium", HIGH: "High" };

/** Field markup used by the forms on phases 2–4 pages. */
export function field(name, label, input, help) {
  return html`<label class="field"><span>${label}</span>${input}
    ${help ? html`<small class="field__help">${help}</small>` : ""}
    <small class="field__error" data-for="${name}"></small></label>`;
}

/** Show server field errors under matching inputs; returns true if any were shown. */
export function showFieldErrors(form, err) {
  let shown = false;
  form.querySelectorAll(".field__error").forEach((slot) => {
    const msg = err.fieldError?.(slot.dataset.for);
    slot.textContent = msg || "";
    if (msg) shown = true;
  });
  return shown;
}

export function clearFieldErrors(form) {
  form.querySelectorAll(".field__error").forEach((slot) => { slot.textContent = ""; });
}

/** Disable a submit button while an async action runs. */
export async function busy(button, label, action) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await action();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
