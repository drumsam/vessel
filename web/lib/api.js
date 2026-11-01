"use client";

// Every call carries the session cookie. The API sets it HttpOnly, so this file
// never sees a token and cannot put one anywhere it would leak.
export const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : detail?.error || JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body) {
  const response = await fetch(BASE + path, {
    method,
    credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, payload?.detail ?? payload);
  return payload;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  put: (path, body) => request("PUT", path, body ?? {}),
  patch: (path, body) => request("PATCH", path, body ?? {}),
  del: (path) => request("DELETE", path),
};

// Money arrives as a string and stays one: parsing it into a Number here would
// be the float the whole system refuses. Only ever formatted for display.
export function money(value, currency = "GBP") {
  if (value === null || value === undefined) return "—";
  const [pounds, pence = "00"] = String(value).split(".");
  const sign = pounds.startsWith("-") ? "-" : "";
  const digits = pounds.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const symbol = { GBP: "£", USD: "$", EUR: "€" }[currency] || currency + " ";
  return `${sign}${symbol}${digits}.${pence}`;
}

export function rate(value) {
  if (value === null || value === undefined) return "—";
  return (Number(value) * 100).toFixed(2).replace(/\.00$/, "") + "%";
}

export function format(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}
