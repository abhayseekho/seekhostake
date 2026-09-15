# Swim Bet — Khuseel vs Bansod live betting portal

Parimutuel pool for the 16 Sept office swim race (best of 3 × 25m). Cash-first: a bet enters the
pool only after the admin (cashier) confirms cash received. Organiser is net-zero by construction —
settlement asserts payouts sum exactly to the pool.

**Rules:** winners get stake back + 70% of the losing pot pro-rata (rounded down); the winning
swimmer gets 30% of the losing pot + rounding remainder. Latest approved bet per person binds.
Betting open pre-race + break 1 only; no side-switching after lap 1; book closes when lap 2 starts.

## Local dev

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/                       # engine invariants
SWIMBET_DEV=1 .venv/bin/uvicorn api:app --port 8000     # auth bypassed, SQLite
cd frontend && npm install && npm run dev               # Vite on :5173, proxies /api + /auth
```

Seed the WhatsApp book: `SWIMBET_DEV=1 .venv/bin/python seed.py` (or the admin "Load WhatsApp book"
button while the pool is empty).

## Deploy (Railway)

1. New Railway project → service from this GitHub repo (Dockerfile at root, auto-deploy on push).
2. Add the Postgres plugin → provides `DATABASE_URL`.
3. Google OAuth web client (GCP console → APIs & Services → Credentials → OAuth client ID, type
   "Web application") with authorized redirect URI `https://<railway-domain>/auth/callback`.
4. Env vars (no secret is ever in the repo):

| var | value |
| --- | --- |
| `SESSION_SECRET` | random 32+ chars |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from the OAuth client |
| `AUTH_REDIRECT_URI` | `https://<railway-domain>/auth/callback` |
| `ALLOWED_DOMAIN` | `seekhoapp.com` |
| `OWNER_EMAILS` | `abhay@seekhoapp.com` (admin/cashier) |

5. Seed once: open the site as owner → admin panel → "Load WhatsApp book".

**Race-morning fallback if OAuth stalls:** set `AUTH_MODE=name` + `ADMIN_PASSWORD=<something>` —
bettors identify by typed name; admin unlocks via the password (POST /auth/admin, the UI asks).
