"""Loopback internal API. Deploy behind authenticated infrastructure for shared use."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit
from ..observations.models import MarketUnit
from ..reference.snapshot import reference


def unit_from(query):
    fields = {k: v[0] for k, v in query.items()}
    fields["bottle_ml"] = int(fields["bottle_ml"])
    fields["pack_size"] = int(fields["pack_size"])
    return MarketUnit(**fields)


def make_server(store, host="127.0.0.1", port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log arbitrary query strings or source evidence.

        def respond(self, code, body):
            encoded = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            path = urlsplit(self.path)
            try:
                if path.path == "/health":
                    with store.connection() as db:
                        db.execute("SELECT 1").fetchone()
                    return self.respond(200, {"status": "ok"})
                if path.path == "/v1/source-runs":
                    return self.respond(200, store.runs())
                if path.path == "/v1/unresolved":
                    return self.respond(200, store.observations(unresolved=True))
                if path.path in {"/v1/reference", "/v1/observations"}:
                    unit = unit_from(parse_qs(path.query, strict_parsing=True))
                    body = reference(store, unit) if path.path.endswith("reference") else store.observations(unit)
                    return self.respond(200, body)
                self.respond(404, {"error": "Unknown route"})
            except (KeyError, TypeError, ValueError):
                self.respond(400, {"error": "Supply an exact market unit: wine_id, vintage, bottle_ml, pack_size, market, tax_status, currency"})
            except Exception:
                self.respond(500, {"error": "Market evidence unavailable"})

        def do_POST(self):
            path = urlsplit(self.path)
            if path.path != "/v1/refresh":
                return self.respond(404, {"error": "Unknown route"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid length")
                unit = MarketUnit(**json.loads(self.rfile.read(length)))
                store.request_refresh(unit)
                self.respond(202, {"status": "queued", "note": "A configured collector worker must process this request"})
            except (ValueError, TypeError):
                self.respond(400, {"error": "Expected exact market unit JSON"})

    return ThreadingHTTPServer((host, port), Handler)
