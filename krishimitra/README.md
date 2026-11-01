# KrishiMitra

Agri-commerce and advisory platform for farmers: farm and crop records, AI crop-disease photo check, AI assistant (English / Hindi / Marathi, voice input), soil testing, a multi-supplier marketplace with wallet, returns, machinery rental and OTP-confirmed delivery, weather-based advisories, IoT sensors with smart irrigation, experts, community, learning and scheme information, support, and admin / district / super-admin / finance / founder / developer portals. Scope follows `docs/FEATURE_LIST.txt` (section 34, future expansion, is intentionally not built).

## Read this first: what is and is not verified

- **This code has not been run end to end.** The environment it was written in could not install Python or npm packages. What was done: `ruff` (undefined names, syntax), `py_compile`, an AST check that every imported model and every model attribute exists, a foreign-key cycle check, an `esbuild` bundle of the frontend, and a `tsc` check against stub React typings. Expect some runtime bugs on first start; fix them before any real use.
- **The test suite has not been executed.** `tests/test_core_flows.py` was written for the current API. `test_crop_doctor.py`, `test_rag.py`, `test_llm_fallback.py` predate the rebuild and may need small updates.
- **"10,000 users" is a design target, not a measurement.** The design choices that support it are listed below. Nobody has load-tested it. `ops/loadtest.py` is only a rough probe; do a real test (k6 / Locust, authenticated mixed traffic, production-sized Postgres) before launch.
- **External services need your keys and are not tested here:** LLM providers (Groq / Mistral / Gemini), Twilio SMS, SMTP email, Razorpay. Without them SMS prints to the log, email is skipped, AI answers fall back to retrieved knowledge text or a "service unavailable" message, and payments are COD or wallet with a *simulated* wallet top-up. **Real payment gateway integration is not done.**
- **Content needs expert review.** Crop advisory ranges are generic and marked "verify locally"; they contain no pesticide or fertiliser doses. Government scheme entries are marked `needs_verification` until an admin confirms them from the official source. Hindi and Marathi UI text is machine-quality and should be reviewed by a native speaker. The disease model needs a trained artifact (`ml/`); without one the app says so instead of guessing.
- Legal, GST and privacy wording are placeholders, not legal advice.

## Run locally

```bash
cp .env.example .env            # set SECRET_KEY and DATA_ENCRYPTION_KEY (see comments in the file)
docker compose up --build       # web on http://localhost:8080, IoT monitor at /iot.html
docker compose exec api python -m app.seed --demo     # base data + fictional demo users (never in production)
```

Without Docker: `cd backend && pip install -r requirements.txt && python -m app.seed --demo && uvicorn app.main:app --reload`, `python -m app.worker` in a second shell, and `cd frontend && npm install && npm run dev` (port 5173, proxies `/api`). With no `DATABASE_URL` the backend uses SQLite, which is fine for development only.

Demo logins (password printed by the seed command, or set `DEMO_PASSWORD`): `farmer@demo.local` / `9000000020`, `expert@`, `supplier@`, `delivery@`, `lab@`, `district@`, `admin@`, `super@`, `finance@`, `developer@`, `founder@` (all `@demo.local`). Seed without `--demo` for production: it only creates roles, permissions, districts, categories and reference content.

Tests: `pip install -r backend/requirements.txt && pytest`. Frontend: `npm test` (vitest).

## Roles and registration

Self-registration: Farmer (mobile + password), Expert (qualification, specialization), Supplier (shop name), Delivery partner (vehicle type, licence number), Soil center. Accounts verify by OTP, then non-farmer roles sit in `PENDING_APPROVAL` with **no permissions** until an admin (or the district manager for their district) approves, after reviewing uploaded documents. Staff roles (Admin, District Manager, Finance, Developer, Founder, Super Admin) cannot self-register; the super admin creates them. Permissions are stored in the database and editable by the super admin; anything not granted is denied.

## Architecture

Modular monolith, so one deployable unit that can be scaled horizontally.

- **API:** FastAPI + SQLAlchemy 2 + PostgreSQL, run by gunicorn with several workers. Stateless: sessions are JWTs backed by a `UserSession` row (so logout and "sign out other devices" really revoke). Cookie sessions need the `X-KM-Client: web` header on writes (CSRF defence).
- **Worker:** `python -m app.worker`, a single instance, handles the notification outbox (SMS/email), scheduled tasks, IoT offline detection and rollups, advisory generation, and raw-data retention. Do not run two.
- **Redis (optional):** shared rate-limit counters when you run more than one API container. Without it, limits are per process.
- **Qdrant:** vector store for the AI knowledge base.
- **Frontend:** React + Vite + TypeScript, plain CSS, no UI framework. Two entry pages: the main app and `iot.html` (IoT monitor). Secrets never reach the browser; all provider keys and the database live behind the API.

Scale-minded decisions: narrow indexed sensor tables with a "latest value" upsert and hourly rollups; devices push over HTTPS with a per-device token and **pull** pump commands (the pump is never reachable from the internet); conditional `UPDATE`s for stock and wallet so concurrent checkouts cannot oversell or overdraw; money in integer paise; paginated lists; weather cached per grid cell; background work off the request path; DB pool sizes set by env. Capacity depends on hardware, so measure.

## Money rules

Payment is COD or wallet. Each cart is split per supplier into separate orders. Suppliers are credited on delivery, net of commission (`COMMISSION_BP`, default 5%). Delivery needs a 4-digit code the farmer reads out; five wrong tries lock the job. Returns refund to the wallet after supplier or admin approval.

## Safety rules for irrigation

The pump runs only if: no manual override conflict, runtime under `max_minutes`, minimum gap since last run, tank level above threshold (if enabled), not raining (if enabled), and sensor data is fresh. Manual commands pause automation for one hour. Treat this as a convenience feature, not a safety system.

## Operations

- `ops/backup.sh` nightly Postgres dump + uploads archive (test restores).
- `ops/check_fk_cycles.py` verifies the schema has no circular foreign keys.
- Migrations: `alembic upgrade head` creates the baseline; use `alembic revision --autogenerate` for later changes.
- Production checklist: set `APP_ENV=production`, strong `SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `COOKIE_SECURE=true`, `OTP_DEV_ECHO=false`, real `CORS_ORIGINS`, TLS in front, managed Postgres with backups, no demo seed.

## Known gaps

No real payment gateway, no push notifications (adapter stub only), no native mobile app (the web app is mobile-friendly), voice uses the browser Web Speech API (quality varies by device and language), disease detection needs a trained model, no formal security audit or load test.
