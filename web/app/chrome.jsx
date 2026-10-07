"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Navigation, and the sign-in gate. Every page below assumes an operator. */
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
    if (settled && session.status === "out" && pathname !== "/login") router.replace("/login");
  }, [settled, session.status, pathname, router]);

  // VESSEL's seller- and buyer-facing screens have no operator session behind
  // them at all (drop one: reachable by the link, like v3/v4 both leave it —
  // KYC and a door policy are named as still-open operational items, not a
  // developer's call to make silently). They never go through this gate.
  // /i/* (the invite landing/accept page) and /member/* (a member's own,
  // link-only page) are the same discipline, extended as far as the
  // referral programme needs it (decision 0025) — a member has no
  // password and no session either.
  if (pathname === "/login" || pathname.startsWith("/vessel")
      || pathname.startsWith("/i/") || pathname.startsWith("/member"))
    return <main>{children}</main>;
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
