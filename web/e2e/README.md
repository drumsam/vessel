# End-to-end smoke test

Drives the operator console against a real API, worker, Postgres and Redis. It
covers the paths no unit test can reach: the session redirect after sign-in, the
job-polling buttons, and what a client-facing document is allowed to say.

The merchant market is seeded straight into Postgres, so the test never touches
a live merchant and always sees the same market.

```bash
# 1. services (docker compose, or any real Postgres and Redis)
docker compose up -d

# 2. schema and an operator
export DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_e2e
alembic upgrade head
python scripts/manage_operators.py add e2e "E2E Operator" --password e2e-password

# 3. the API and a worker (macOS needs the non-forking worker)
FRONTEND_ORIGINS=http://localhost:3077 INSECURE_COOKIES=1 \
  uvicorn app.api.main:app --port 8077 &
RQ_WORKER_CLASS=simple python -m app.worker &

# 4. the app, pointed at the API on the SAME host: a SameSite=Lax cookie is not
#    sent cross-site, so localhost:3077 -> 127.0.0.1:8077 would silently fail
NEXT_PUBLIC_API_URL=http://localhost:8077 npm run dev -- -p 3077 &

# 5. the test
E2E_DATABASE_URL=$DATABASE_URL npm run e2e
```
