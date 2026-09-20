# Operator frontend

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The API sets an `HttpOnly` session cookie, so every request is sent with
`credentials: "include"` and the API must list this origin in
`FRONTEND_ORIGINS`. For local HTTP development the API also needs
`INSECURE_COOKIES=1`, because the cookie is `Secure` by default.

Screens: deals and upload (`/`), one deal (`/deals/<id>`), the exception queue
(`/queue`), an issued offer (`/offers/<id>`).

The seller's spreadsheet is parsed here, in the browser. The original row is
sent verbatim as `raw_row` and the API refuses a line without one.
