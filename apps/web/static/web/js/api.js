// API client shared by every page. Talks to the same /api/v1/ as the mobile app.
//
// Tokens: the access token lives only in memory. The refresh token is kept in
// sessionStorage so a page reload keeps you signed in, but closing the tab
// signs you out. The page's strict Content-Security-Policy (no inline
// scripts) protects both from injected code.

const BASE = document.body.dataset.apiBase || "/api/v1/";
const REFRESH_KEY = "p2plend.refresh";

let accessToken = null;
let refreshInFlight = null;

export class ApiError extends Error {
  constructor({ code, message, status = 0, details = {}, requestId = null }) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }

  get isNetwork() { return this.code === "network_error"; }

  fieldError(field) {
    const v = this.details?.[field];
    if (Array.isArray(v) && v.length) return String(v[0]);
    return typeof v === "string" ? v : null;
  }
}

const getRefresh = () => {
  try { return sessionStorage.getItem(REFRESH_KEY); } catch { return null; }
};
const setRefresh = (token) => {
  try { sessionStorage.setItem(REFRESH_KEY, token); } catch { /* storage unavailable */ }
};

export function clearSession() {
  accessToken = null;
  try { sessionStorage.removeItem(REFRESH_KEY); } catch { /* ignore */ }
}

export const hasStoredSession = () => Boolean(getRefresh());

function toError(res, body) {
  const e = body && body.error;
  if (e) {
    return new ApiError({
      code: e.code, message: e.message, status: res.status, details: e.details || {}, requestId: e.request_id,
    });
  }
  return new ApiError({
    code: `http_${res.status}`, message: `The server returned an unexpected response (${res.status}).`, status: res.status,
  });
}

async function send(path, { method = "GET", body, auth = true, query } = {}) {
  const headers = { Accept: "application/json" };
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let url = BASE + path;
  if (query) {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== "" && v != null));
    if ([...qs].length) url += `?${qs}`;
  }
  let res;
  try {
    res = await fetch(url, {
      method, headers, credentials: "same-origin",
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError({ code: "network_error", message: "Can't reach the server. Check your connection and try again." });
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  return { res, data };
}

/** Exchange the refresh token for new tokens. One call even if many requests hit 401 together. */
function refreshTokens() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const refresh = getRefresh();
      if (!refresh) return false;
      const { res, data } = await send("auth/token/refresh/", { method: "POST", body: { refresh }, auth: false });
      if (res.ok) {
        accessToken = data.access;
        setRefresh(data.refresh || refresh);
        return true;
      }
      if (res.status === 401) clearSession();
      return false;
    })().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

export async function request(path, opts = {}) {
  let { res, data } = await send(path, opts);
  if (res.status === 401 && opts.auth !== false && getRefresh()) {
    if (await refreshTokens()) {
      ({ res, data } = await send(path, opts));
    } else {
      window.dispatchEvent(new CustomEvent("p2p:session-expired"));
    }
  }
  if (!res.ok) {
    const err = toError(res, data);
    // The server blocks everything except sign-in and the terms until they are accepted.
    if (err.code === "terms_not_accepted") window.dispatchEvent(new CustomEvent("p2p:terms-required", { detail: err }));
    throw err;
  }
  return data;
}

export const api = {
  get: (path, query) => request(path, { query }),
  post: (path, body = {}) => request(path, { method: "POST", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  del: (path, body) => request(path, { method: "DELETE", body }),
  upload: (path, formData) => request(path, { method: "POST", body: formData }),
};

/** API URLs returned by the server (e.g. "/api/v1/kyc/...") -> path relative to BASE. */
const relative = (url) => (url.startsWith(BASE) ? url.slice(BASE.length) : url.replace(/^\/api\/v1\//, ""));

/** Fetch a protected file (KYC or loan document) with the access token and return a Blob. */
export async function fetchFile(url) {
  const attempt = () => fetch(BASE + relative(url), {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {}, credentials: "same-origin",
  });
  let res = await attempt();
  if (res.status === 401 && (await refreshTokens())) res = await attempt();
  if (!res.ok) throw new ApiError({ code: `http_${res.status}`, message: "This file couldn't be opened.", status: res.status });
  return res.blob();
}

/** Signed-out registration; stores the new session like login does. */
export async function register(data) {
  const result = await request("auth/register/", { method: "POST", body: data, auth: false });
  accessToken = result.access;
  setRefresh(result.refresh);
  return result.user;
}

export async function login(email, password) {
  const data = await request("auth/token/", { method: "POST", body: { email: email.trim(), password }, auth: false });
  accessToken = data.access;
  setRefresh(data.refresh);
  return data.user;
}

export async function logout() {
  const refresh = getRefresh();
  try {
    if (refresh) await request("auth/logout/", { method: "POST", body: { refresh } });
  } catch { /* still sign out locally */ }
  clearSession();
}

/** On page load: turn a stored refresh token back into a session. */
export async function restoreSession() {
  if (!getRefresh()) return null;
  if (!(await refreshTokens())) return null;
  return request("accounts/me/");
}

export const health = () => request("health/", { auth: false });
