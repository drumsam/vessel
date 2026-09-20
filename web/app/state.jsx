"use client";

/** One line's state, in the words the API uses. NOT_SEARCHED is not NO_MARKET. */
export const STATE_LABEL = {
  IDENTITY_NOT_APPROVED: ["Identity not approved", "plain"],
  NOT_SEARCHED: ["Not searched", "plain"],
  READY: ["Ready", "ready"],
  REVIEW: ["Review", "review"],
  NO_MARKET: ["No market", "stop"],
};

export function StateTag({ state }) {
  const [label, tone] = STATE_LABEL[state] || [state, "plain"];
  return <span className={`tag ${tone}`}>{label}</span>;
}

export function Flags({ flags, tone = "plain" }) {
  if (!flags || !flags.length) return null;
  return flags.map((flag) => (
    <span className={`tag ${tone}`} key={flag}>{flag.replaceAll("_", " ").toLowerCase()}</span>
  ));
}
