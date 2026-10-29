"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Navigation, and the sign-in gate. Every page below assumes an operator. */
/** Paths with no operator session behind them at all: VESSEL's seller- and
 * buyer-facing screens, a member's own invite/landing pages (decision
 * 0025), and a shared public offer link (decision 0035) — all reachable
 * by an anonymous visitor who has never signed in and never will. Read
 * by BOTH the redirect effect and the render below; checking it only in
 * the render left the effect still firing `router.replace("/login")` out
 * from under a public page the instant its own session check came back
 * "out" — which it always does, for a visitor with no cookie at all. */
function isPublicPath(pathname) {
  return pathname === "/login" || pathname.startsWith("/vessel")
      || pathname.startsWith("/i/") || pathname.startsWith("/member")
      || pathname.startsWith("/share/");
}

export default function Chrome({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  // The check is redone on every navigation, and nothing is decided from a
  // stale answer: signing in navigates to "/", and a left-over "signed out"
  // from the login page's own check would otherwise bounce straight back.
  // The check is redone on every navigation, and it records WHICH path it was
  // made for. Signing in navigates from /login to /, and an answer that belongs
  // to the page we just left must not decide anything about the one we are on:
  // that is what bounced a freshly signed-in operator back to /login.
  const [session, setSession] = useState({ status: "checking", operator: null, path: null });

  useEffect(() => {
    let current = true;
    api.get("/session")
      .then((operator) => current && setSession({ status: "in", operator, path: pathname }))
      .catch(() => current && setSession({ status: "out", operator: null, path: pathname }));
    return () => { current = false; };
  }, [pathname]);

  const settled = session.path === pathname;

  useEffect(() => {
    if (settled && session.status === "out" && !isPublicPath(pathname)) router.replace("/login");
  }, [settled, session.status, pathname, router]);

  if (isPublicPath(pathname)) return <main>{children}</main>;
  if (!settled) return <main><p className="muted">Loading…</p></main>;
  if (session.status === "out") return <main><p className="muted">Signing in…</p></main>;
  const operator = session.operator;

  const link = (href, label) => (
    <Link href={href} className={pathname === href ? "on" : ""}>{label}</Link>
  );

  return (
    <>
      <header className="top">
        <div className="inner">
          <span className="brand">UK Fine Wine Pricer</span>
          <nav>
            {link("/", "Deals")}
            {link("/pocket", "Pocket")}
            {link("/queue", "Exceptions")}
          </nav>
          <span className="who">
            {operator.display_name}{" · "}
            <a href="#" onClick={async (e) => {
              e.preventDefault();
              await api.del("/session");
              router.replace("/login");
            }}>sign out</a>
          </span>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
