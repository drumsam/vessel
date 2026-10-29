"""Anthropic provider. The first real implementation in `app/ai/` -- the
other three names (openai, gemini) stay the stubs in `_stub.py`.

Only `propose_inbound_offer` (VESSEL Pocket, build brief Phase 1b step 2)
is implemented here. The other four capabilities are not exercised by
anything built yet; each raises plainly rather than pretending to work.

`ANTHROPIC_API_KEY` comes from the environment alone -- set by Doug
directly on the hosting platform, the same discipline as `DATABASE_URL`.
Its absence is a loud, named failure, never a silent fallback to a
regex parser: a provider outage must read as "couldn't read this," not
as a quieter, worse parser taking over unannounced.

Structured outputs, not forced tool use: Sonnet 5.5 (and the rest of the
5.x/Fable 5.1 generation) 400s on `tool_choice={"type": "tool"|"any"}`
outright -- confirmed live, 28 October 2026. `client.messages.parse()`
with a Pydantic `output_format` is the documented replacement for
exactly this "one fixed JSON shape" job, needs no beta header (unlike
the deprecated `output_format=` request body field, not to be confused
with this SDK method's own `output_format=` keyword, which builds the
right `output_config` for you), and is the mechanism this file uses.

`_ProposalWire` is the wire shape -- provider-internal, never crosses
`propose_inbound_offer`'s own return boundary. `provider.py`'s rule is
that `InboundOfferProposal` is the seam; nothing provider-specific,
Pydantic included, is allowed to leak past this module.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Literal, NoReturn, Optional

import anthropic
from pydantic import BaseModel, ConfigDict

from .provider import (AIProvider, CompReview, ConditionParse, IdentityProposal,
                       IdentityVerdict, InboundOfferProposal, Provenance)

#: Already pinned, not a floating alias (decision 0045): from the 4.6
#: generation onward Anthropic dropped dated snapshots -- this dateless
#: id IS the snapshot, documented to behave the same for its whole life.
#: The residual risk is retirement, not drift, and decision 0040's
#: three-state handling already turns that into a visible, blocking
#: failure rather than a silent one. Do not "fix" this into a dated form
#: that was never issued.
DEFAULT_MODEL = "claude-sonnet-5-5"

#: Reinforces, in the model's own instructions, exactly the rule the brief
#: states as non-negotiable: propose, never invent. Every field but
#: category and reasoning is optional in the schema; this is what stops
#: the model filling one in anyway.
SYSTEM_PROMPT = """You read one inbound wine or whisky offer -- pasted text, a \
photographed label, or an uploaded file -- and report ONLY facts explicitly \
present in it, as the one JSON object described to you.

Rules, all of them hard:
- Never infer, estimate, compute, or default a value. If the source does not \
state a field, omit it (send null) -- do not guess "OWC" for packaging, do not \
guess a bond status, do not round or convert a price.
- A seller's asking price may only be reported if a figure is literally written \
in the source, exactly as written, labelled as the seller's ask. Never compute, \
average, or infer one. If no figure appears, asking_price is null.
- You never produce a reference price, a buyer price, a margin, or any verdict \
on whether the offer is good. There is no field for one; do not put it in reasoning.
- category is "whisky" if the text or image describes a distillery, an \
independent bottler, a cask number, or an age statement rather than a wine \
producer and cuvee. category is "unknown" if you cannot identify the item as \
either wine or whisky. Otherwise category is "wine".
- vintage and bottle_ml are integers when stated and null when not.
- pack_size is bottles per commercial unit (a single bottle is pack_size=1; \
a case of six is pack_size=6) and quantity is the number of those units -- \
NOT a bottle count. Set both ONLY when the source is unambiguous about which \
commercial unit it means: "3 individual bottles" is pack_size=1, quantity=3; \
"1 case of 6" or "1 OWC of 6" is pack_size=6, quantity=1.
- If the source states a bottle count but you cannot tell whether it is one \
case or that many loose bottles (e.g. "6 x [wine] OWC" with nothing further), \
leave BOTH pack_size and quantity null and set total_bottles to the bottle \
count instead. Do not guess the split -- that is a fact only a person can \
resolve, not you.
- asking_basis is "per_bottle", "per_case", or "total" -- ONLY when the \
source says so explicitly ("a bottle", "per bottle", "the case", "in total", \
"for the lot"). Never infer it from quantity or pack_size; a price with no \
stated unit gets asking_basis=null, however many bottles are involved.
- reasoning is one brief sentence on what was read; if category is whisky or \
unknown, say why.
"""


class _ProposalWire(BaseModel):
    """Validates the response text on OUR side only -- it no longer
    generates the request schema (see PROPOSAL_SCHEMA below for why).
    `extra="forbid"` still rejects anything the model invents outside
    these fields."""
    model_config = ConfigDict(extra="forbid")

    category: Literal["wine", "whisky", "unknown"]
    producer: Optional[str] = None
    cuvee: Optional[str] = None
    vintage: Optional[int] = None
    bottle_ml: Optional[int] = None
    pack_size: Optional[int] = None
    quantity: Optional[int] = None
    total_bottles: Optional[int] = None
    bond_status: Optional[str] = None
    stock_location: Optional[str] = None
    packaging: Optional[str] = None
    asking_price: Optional[str] = None
    asking_currency: Optional[str] = None
    asking_basis: Optional[Literal["per_bottle", "per_case", "total"]] = None
    reasoning: str


#: Hand-written, not derived from _ProposalWire. Found live, 29-30
#: October 2026: "Error code: 400 - Schema is too complex" from
#: Anthropic's own structured-outputs compiler, intermittently --
#: after this schema grew to 14 fields when total_bottles/asking_basis
#: were added. Anthropic compiles a schema into a constrained grammar,
#: and complexity there is driven far more by the NUMBER of `anyOf`
#: branches than by raw size: Pydantic's default `Optional[X] = None`
#: emits `{"anyOf": [{"type": X}, {"type": "null"}]}` for every one of
#: the twelve optional fields here, each one its own branch. JSON
#: Schema's type-ARRAY form (`"type": [X, "null"]`) is semantically
#: identical and expresses the exact same "stated or null, never
#: guessed" rule this schema exists to enforce -- but it is a single
#: type constraint, not a union, and compiles far cheaper. No `title`,
#: no `default` keys either: both are schema text Pydantic adds that
#: buys nothing here and were stripped along with the anyOf rewrite.
PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "reasoning"],
    "properties": {
        "category": {"type": "string", "enum": ["wine", "whisky", "unknown"]},
        "producer": {"type": ["string", "null"]},
        "cuvee": {"type": ["string", "null"]},
        "vintage": {"type": ["integer", "null"]},
        "bottle_ml": {"type": ["integer", "null"]},
        "pack_size": {"type": ["integer", "null"]},
        "quantity": {"type": ["integer", "null"]},
        "total_bottles": {"type": ["integer", "null"]},
        "bond_status": {"type": ["string", "null"]},
        "stock_location": {"type": ["string", "null"]},
        "packaging": {"type": ["string", "null"]},
        "asking_price": {"type": ["string", "null"]},
        "asking_currency": {"type": ["string", "null"]},
        "asking_basis": {"type": ["string", "null"],
                         "enum": ["per_bottle", "per_case", "total", None]},
        "reasoning": {"type": "string"},
    },
}


def _not_built_yet(capability: str) -> NoReturn:
    raise NotImplementedError(
        f"AnthropicProvider.{capability} is not implemented: nothing built yet calls it. "
        "Only propose_inbound_offer (VESSEL Pocket) is implemented so far.")


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, model: str = "") -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it on the hosting platform directly -- "
                "this never falls back to a different parser.")
        self._model = model or DEFAULT_MODEL
        # The SDK's own default is a 10-minute timeout with 2 retries --
        # fine for a long-running script, fatal here: Vercel kills this
        # function at 60s (vercel.json's maxDuration) with NO response
        # ever sent to the browser, which is "taking forever and not
        # fetching" from Doug's side, not a clean 502 decision 0040's
        # own three-state handling could catch. Found live, 29 October
        # 2026, from repeated "Task timed out after 60 seconds" errors
        # with zero preceding application log line -- the call was still
        # in flight when Vercel killed the whole process.
        #
        # 20s, 0 retries: comfortably under the function's own ceiling,
        # leaving room for everything else in the request, and a fast,
        # controlled failure the operator can retry from the UI is
        # strictly better than a silent one the SDK was still "handling".
        self._client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=0)

    def propose_inbound_offer(self, raw_body: Optional[str], raw_media: Optional[bytes],
                              media_mime: Optional[str]) -> InboundOfferProposal:
        content: list[dict[str, Any]] = []
        if raw_media:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_mime or "image/jpeg",
                          "data": base64.b64encode(raw_media).decode("ascii")},
            })
        if raw_body:
            content.append({"type": "text", "text": raw_body})
        if not content:
            raise ValueError("propose_inbound_offer needs raw_body or raw_media")

        response = self._client.messages.create(
            model=self._model, max_tokens=4096, system=SYSTEM_PROMPT,
            # Sonnet 5.5 has adaptive thinking on by default, and thinking
            # tokens count toward max_tokens -- pure field extraction earns
            # nothing from it. Must be sent alone; any other key in this
            # dict 400s.
            thinking={"type": "between_tools"},
            messages=[{"role": "user", "content": content}],
            # The hand-written PROPOSAL_SCHEMA, not output_format=_ProposalWire:
            # letting the SDK derive the schema from the Pydantic class is what
            # produced the anyOf-heavy schema Anthropic rejected as "too
            # complex" -- see PROPOSAL_SCHEMA's own comment. .create(), not
            # .parse(): there is no type here for the SDK to auto-parse
            # against, so the text block is read and validated by hand below.
            output_config={"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
        )

        # "refusal" and "max_tokens" both produce output that does not
        # reliably match the schema -- max_tokens in particular can leave
        # JSON mid-field, which model_validate_json() below might still
        # accept as a technically-parseable but WRONG shorter value.
        # Checked before the text block is ever trusted, not after.
        if response.stop_reason != "end_turn":
            raise RuntimeError(f"Anthropic stopped early: stop_reason={response.stop_reason!r}")

        # Read by type, never by index: a thinking block (none expected
        # here with thinking disabled, but never assumed) carries an
        # empty text field, so content[0].text would silently break.
        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block is None:
            raise RuntimeError("Anthropic response carried no text block")
        wire = _ProposalWire.model_validate_json(text_block.text)

        provenance = Provenance(provider=self.name, model=self._model)
        return InboundOfferProposal(
            category=wire.category, producer=wire.producer, cuvee=wire.cuvee,
            vintage=wire.vintage, bottle_ml=wire.bottle_ml, pack_size=wire.pack_size,
            quantity=wire.quantity, total_bottles=wire.total_bottles,
            bond_status=wire.bond_status, stock_location=wire.stock_location,
            packaging=wire.packaging, asking_price=wire.asking_price,
            asking_currency=wire.asking_currency, asking_basis=wire.asking_basis,
            reasoning=wire.reasoning, provenance=provenance)

    def resolve_wine_identity(self, raw_description: str, context: dict[str, Any]) -> IdentityProposal:
        _not_built_yet("resolve_wine_identity")

    def review_wine_identity(self, raw_description: str, proposal: IdentityProposal,
                             context: dict[str, Any]) -> IdentityVerdict:
        _not_built_yet("review_wine_identity")

    def review_comparables(self, line: dict[str, Any], accepted: list[dict[str, Any]],
                           rejected: list[dict[str, Any]]) -> CompReview:
        _not_built_yet("review_comparables")

    def parse_condition(self, text: str) -> ConditionParse:
        _not_built_yet("parse_condition")
