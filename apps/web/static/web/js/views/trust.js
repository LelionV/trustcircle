import { api } from "../api.js";
import { formatDate, formatDateTime, html, mount, raw } from "../ui.js";
import { loadingBlock, pageHead } from "./common.js";
import { layoutRuler, ruler } from "./ruler.js";
import { rateText } from "./shared.js";

/** Score over time as a small SVG line chart (attributes only, so the strict CSP is fine). */
export function scoreChart(history) {
  const points = [...history].reverse().filter((e) => e.score_after !== null);
  if (points.length < 2) return html`<p class="muted small">The chart appears once your score has changed.</p>`;
  const W = 640, H = 180, PAD = 28;
  const x = (i) => PAD + (i * (W - PAD * 2)) / (points.length - 1);
  const y = (v) => H - PAD - (v * (H - PAD * 2)) / 100;
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.score_after).toFixed(1)}`).join(" ");
  const grid = [0, 50, 100].map((v) => `<line x1="${PAD}" x2="${W - PAD}" y1="${y(v)}" y2="${y(v)}" class="chart__grid"/>`
    + `<text x="${PAD - 6}" y="${y(v) + 4}" class="chart__axis" text-anchor="end">${v}</text>`).join("");
  const dots = points.map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p.score_after).toFixed(1)}" r="3.5" class="chart__dot"><title>${p.score_after}</title></circle>`).join("");
  const first = formatDate(points[0].at), last = formatDate(points[points.length - 1].at);
  return html`<figure class="chart">
    ${raw(`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Trust score history">${grid}<polyline points="${line}" class="chart__line"/>${dots}</svg>`)}
    <figcaption class="chart__caption"><span>${first}</span><span>${last}</span></figcaption>
  </figure>`;
}

export function componentRows(breakdown) {
  const rows = breakdown?.components || [];
  return html`<table class="table table--plain">
    <thead><tr><th scope="col">What counts</th><th scope="col">Weight</th><th scope="col">Your score</th><th scope="col">Why</th></tr></thead>
    <tbody>${rows.map((c) => html`<tr>
      <td>${c.label}</td><td>${c.weight}%</td>
      <td class="nowrap">${c.score === null ? html`<span class="muted">Not scored yet</span>`
        : html`<meter min="0" max="100" low="40" high="70" optimum="100" value="${c.score}">${c.score}</meter> ${c.score}`}</td>
      <td class="small">${c.detail}</td>
    </tr>`)}</tbody>
  </table>
  ${(breakdown?.adjustments || []).length ? html`<h3>Adjustments</h3><ul class="ticks">${breakdown.adjustments.map((a) =>
    html`<li>${a.label}: ${a.points > 0 ? "+" : ""}${a.points} points</li>`)}</ul>` : ""}`;
}

const BANDS = [
  ["early_7_plus", "7 or more days early"], ["early_3_6", "3–6 days early"], ["early_1_2", "1–2 days early"],
  ["on_time", "On the due date"], ["late_1_3", "1–3 days late"], ["late_4_7", "4–7 days late"],
  ["late_8_14", "8–14 days late"], ["late_15_plus", "More than 14 days late"],
];

export async function trustView(el) {
  mount(el, html`${pageHead("Trust score")}${loadingBlock()}`);
  const [t, pricing] = await Promise.all([api.get("trust/me/"), api.get("pricing/brackets/")]);

  if (!t.is_scored) {
    mount(el, html`${pageHead("Trust score", "Your score decides your interest rate.")}
      <section class="panel"><h2>Not scored yet</h2><p>${t.not_scored_reason}</p>
        <a class="btn" href="#/kyc">Go to identity verification</a></section>`);
    return;
  }

  const change = t.change === null ? null : t.change;
  const b = t.breakdown || {};
  mount(el, html`
    ${pageHead("Trust score", "Pay installments early and on time to move into a cheaper bracket for your next loan.")}
    <section class="panel panel--feature score-hero">
      <div class="score-hero__number">
        <p class="score-hero__value">${t.score}</p>
        <p class="score-hero__meta">out of 100</p>
        ${change ? html`<p class="score-hero__meta"><span class="${change > 0 ? "up" : "down"}">${change > 0 ? "+" : ""}${change}</span> since the last change</p>` : ""}
      </div>
      <div class="score-hero__facts">
        <p><strong>${t.bracket?.label || "No bracket"} bracket.</strong> ${t.bracket?.annual_rate ? html`Your next loan would cost ${rateText(t.bracket.annual_rate, t.rate_basis)}.` : "Your rate is set by our credit team."}</p>
        <p>${t.next_bracket
          ? html`Reach <strong>${t.next_bracket.min_score}</strong> (${t.next_bracket.points_needed} more points) for ${t.next_bracket.label.toLowerCase()} at ${rateText(t.next_bracket.annual_rate, t.rate_basis)}.`
          : "You're in the best bracket."}</p>
        <p class="muted small">Confidence: ${t.confidence_label}. ${t.confidence === "NEW"
          ? `New borrowers start at ${b.initial_score ?? 50}; your repayments gradually take over.`
          : `Your repayment history makes up ${b.blend}% of the score.`} Last assessed ${formatDateTime(t.last_assessed_at)}.</p>
      </div>
    </section>
    <section class="panel" id="ruler-panel">
      <h2>Where you are</h2>
      ${ruler(pricing, { marker: { score: t.score, label: `You: ${t.score}` } })}
    </section>
    <div class="columns">
      <section class="panel">
        <h2>Repayment record</h2>
        <dl class="tally tally--compact">
          <div class="tally__item"><dt>Early</dt><dd>${t.counts.early}</dd></div>
          <div class="tally__item"><dt>On time</dt><dd>${t.counts.on_time}</dd></div>
          <div class="tally__item"><dt>Late</dt><dd>${t.counts.late}</dd></div>
          <div class="tally__item"><dt>Loans repaid</dt><dd>${t.counts.completed_loans}</dd></div>
          <div class="tally__item"><dt>Defaults</dt><dd>${t.counts.defaults}</dd></div>
        </dl>
        <h3>Score over time</h3>
        ${scoreChart(t.history)}
      </section>
      <section class="panel">
        <h2>How points work</h2>
        <table class="kv">${BANDS.map(([key, label]) => {
          const pts = t.rules.punctuality_points[key];
          return html`<tr><th scope="row">${label}</th><td>${pts > 0 ? "+" : ""}${pts}</td></tr>`;
        })}</table>
        <p class="small muted">Only full scheduled installments of at least KES ${t.rules.min_installment_amount} count, and one loan can earn at most ${t.rules.reward_cap_per_loan} bonus points, so splitting payments doesn't help. A default costs ${t.rules.default_penalty} points.${t.rules.early_completion_bonus ? ` Repaying a whole loan at least ${t.rules.early_completion_bonus.min_days_early} days before its final due date earns ${t.rules.early_completion_bonus.points} extra points.` : ""}</p>
      </section>
    </div>
    <section class="panel">
      <h2>What makes up your score</h2>
      ${componentRows(b)}
    </section>
    <section class="panel">
      <h2>Every change</h2>
      ${t.history.length ? html`<table class="table table--plain">
        <thead><tr><th scope="col">When</th><th scope="col">What happened</th><th scope="col">Score</th></tr></thead>
        <tbody>${t.history.map((e) => html`<tr>
          <td class="nowrap">${formatDateTime(e.at)}</td>
          <td>${e.reason}</td>
          <td class="nowrap">${e.score_before ?? "–"} → <strong>${e.score_after ?? "–"}</strong>${e.change ? html` <span class="${e.change > 0 ? "up" : "down"}">(${e.change > 0 ? "+" : ""}${e.change})</span>` : ""}</td>
        </tr>`)}</tbody></table>` : html`<p class="muted">No changes yet.</p>`}
    </section>`);
  layoutRuler(el);
}
