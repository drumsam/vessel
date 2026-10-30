"""Local browser-test API. Parser and merchant transport are explicit fixtures.

Run only with a dedicated local *_e2e database; never deploy this harness.
"""

import os
from urllib.parse import urlsplit
from datetime import datetime, timezone
import uvicorn
from app.api.main import app
import app.api.inbound as inbound
from app.ai.provider import InboundOfferProposal, Provenance
from app.worker import jobs
from tests.test_service import bi_card

url = urlsplit(os.environ["DATABASE_URL"])
if url.hostname not in {"localhost", "127.0.0.1"} or not url.path.endswith("_e2e"):
    raise RuntimeError(
        "Browser fixture server requires a disposable local *_e2e database"
    )


class ParserFixture:
    def propose_inbound_offer(self, raw_body, raw_media, media_mime):
        return InboundOfferProposal(
            category="wine",
            producer="Domaine Armand Rousseau",
            cuvee="Charmes-Chambertin Grand Cru",
            vintage=2011,
            bottle_ml=750,
            pack_size=1,
            quantity=1,
            total_bottles=1,
            bond_status="UK In Bond",
            stock_location=None,
            packaging=None,
            asking_price="500",
            asking_currency="GBP",
            asking_basis="per_bottle",
            reasoning="Explicit offline parser fixture",
            provenance=Provenance(provider="fixture", model="fixture"),
        )


inbound.get_provider = lambda: ParserFixture()
original_collect = jobs.collect_now


def fixture_collect(wine_id, vintage):
    return original_collect(
        wine_id,
        vintage,
        merchant_ids=["bordeaux-index"],
        fetch=lambda adapter, params, year: [bi_card("650.00", vintage=year)],
        robots=lambda url: None,
    )


jobs.collect_now = fixture_collect
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8077)
