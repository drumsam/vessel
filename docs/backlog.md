# Backlog — agreed, not built

Requirements Doug has agreed and asked to keep registered for later. None is
in scope until he asks for it by name; a phase may touch one only where it is
structurally necessary, and says so. Registered 1 November 2026.

1. **Global VESSEL search** across wines, suppliers, clients, offers, trades
   and references.
2. **Trade master page**: one clean page per trade showing Status, Supplier,
   Client, Wine, Pricing, Gross, Source, Offer and Ops. (Decision 0050's
   Trades list and Pocket pricing screen are the stepping stones, not this.)
3. **Counterparty admin details**: legal entity, billing/invoice details,
   tax/VAT where relevant, payment/bank information where appropriate, and
   warehouse/delivery defaults. Must never make rapid trade capture
   cumbersome: capture stays name-only (decision 0050).
4. **Admin/Ops desk**: supplier PO, supplier invoice, client invoice,
   warehouse instruction, payment/transfer status, trade documents and a
   simple work queue.
5. **Pricing enrichment**: recent auction history, especially the last three
   years (iDealwine, Sotheby's, Christie's, Heritage, Zachys and other useful
   sources — subject to each source's own access position, decision 0042);
   10–15 trusted merchants; historical pricing and cycle context.
6. **Automated delivery from external pricing providers** (MrBridge and
   similar) into the generic market-evidence pipe (decision 0048), so Doug no
   longer downloads and posts datasets by hand.
7. **Client Wants** — low priority. Client-specific wine wants (client, wine,
   vintage, format, quantity, target price, urgency, notes), periodically
   searched against market sources, with matches and new suppliers surfaced.
   Named "Client Wants", not "want list": decision 0038's want list is the
   producer-identity register (`wine.want_list`), a different thing.
