"use client";

// A member's own page (decision 0025) — no login, reachable by the link,
// handed to them once right after accepting. The one button the share
// spec asks for: a wa.me link with pre-filled text, plus a plain copy
// link for WeChat and group chats.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "../../../lib/api";

export default function MemberPage() {
  const { memberId } = useParams();
  const [member, setMember] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get(`/members/${memberId}`).then(setMember).catch((e) => setError(e.message));
  }, [memberId]);

  if (error) return <div className="notice bad" style={{ margin: "4vh auto", maxWidth: 420 }}>{error}</div>;
  if (!member) return <p className="muted" style={{ margin: "4vh auto", maxWidth: 420 }}>Loading…</p>;

  const inviteUrl = member.open_invite_code && typeof window !== "undefined"
    ? `${window.location.origin}/i/${member.open_invite_code}` : null;
  const firstName = (member.display_name || "there").split(" ")[0];
  const shareText = inviteUrl
    ? `${firstName} here — I buy fine wine through VESSEL, a private sale. Thought you'd want a look: ${inviteUrl}`
    : "";

  return (
    <div style={{ maxWidth: 420, margin: "8vh auto" }}>
      <h1>Hello, {firstName}.</h1>

      {member.early_access_until && new Date(member.early_access_until) > new Date() && (
        <p className="notice" style={{ fontSize: 14 }}>
          You have first look at the next cellar until{" "}
          {new Date(member.early_access_until).toLocaleString("en-GB")}.
        </p>
      )}

      {inviteUrl ? (
        <div className="card">
          <p>You have one invitation to share.</p>
          <button type="button" style={{ width: "100%", marginBottom: 8 }}
                  onClick={() => window.open(`https://wa.me/?text=${encodeURIComponent(shareText)}`, "_blank")}>
            Share on WhatsApp
          </button>
          <button type="button" className="small" style={{ width: "100%" }}
                  onClick={() => {
                    navigator.clipboard?.writeText(inviteUrl);
                    setCopied(true);
                  }}>
            {copied ? "Copied" : "Copy link"}
          </button>
        </div>
      ) : (
        <p className="muted">
          {member.first_purchase_at
            ? "You've already used your invitation — your next one arrives once someone you invited buys."
            : "Your first purchase unlocks an invitation to share."}
        </p>
      )}

      <p className="muted" style={{ fontSize: 12, marginTop: 24 }}>
        Bookmark this page — it&rsquo;s the only way back to it.
      </p>
    </div>
  );
}
