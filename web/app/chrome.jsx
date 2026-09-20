"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Navigation, and the sign-in gate. Every page below assumes an operator. */
export default function Chrome({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  const [operator, setOperator] = useState(undefined);

  useEffect(() => {
    api.get("/session").then(setOperator).catch(() => setOperator(null));
  }, [pathname]);

  useEffect(() => {
    if (operator === null && pathname !== "/login") router.replace("/login");
  }, [operator, pathname, router]);

  if (pathname === "/login") return <main>{children}</main>;
  if (operator === undefined) return <main><p className="muted">Loading…</p></main>;
  if (operator === null) return <main><p className="muted">Signing in…</p></main>;

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
