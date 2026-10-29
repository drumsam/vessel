/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  // The deployed web and API are two separate Vercel projects (origins),
  // so the session cookie -- SameSite=Lax, no Domain, by design -- would
  // never come back on a cross-origin fetch, and Safari on iOS blocks
  // third-party cookies outright regardless. This proxies /api/* through
  // the SAME origin the browser already trusts, server-side, so the
  // browser never sees a cross-origin request at all: the cookie becomes
  // first-party and SameSite=Lax just works. API_ORIGIN is server-only
  // (never NEXT_PUBLIC_*); it names the other Vercel project.
  // Local dev (scripts/desk.sh) never sets API_ORIGIN -- NEXT_PUBLIC_API_URL
  // falls back to an absolute http://localhost:8000 there instead, so
  // nothing ever requests /api/*. Registering the rewrite anyway crashes
  // `next dev`/`next build` outright ("destination does not start with
  // / http:// or https://", since the unset var stringifies to the
  // literal "undefined") -- found running next dev locally, the exact
  // thing this app's own scripts/desk.sh depends on every day.
  async rewrites() {
    if (!process.env.API_ORIGIN) return [];
    return [{ source: "/api/:path*", destination: `${process.env.API_ORIGIN}/:path*` }];
  },
};
