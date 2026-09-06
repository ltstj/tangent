# Tangent backend (FastAPI)

The recommendation engine and API. Phase 0 is a skeleton (`/health`, `/ready`);
the catalog ingest, search, and recommender come in Phase 1 (see `../ROADMAP.md`).

## Run (local)
```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use . .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env    # then fill in your keys (never commit .env)
uvicorn app.main:app --reload
```
- `GET /health` returns `{status: ok}`
- `GET /ready` returns which integrations have keys configured (booleans only, no secrets echoed)

## Config
All keys and URLs come from environment (`app/config.py` reads `../.env`). Nothing
secret is committed. TMDB, IGDB, and Supabase need keys; Open Library and
CheapShark do not.
