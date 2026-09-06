# Tangent frontend (React + Vite)

A small SPA over the Tangent API: search for titles you love (autocomplete), add
them as favorites, choose a target medium (or "Anything" for the cross-media
jump), and get recommendations with a match score and a short "why."

## Run (local)
```bash
cd frontend
npm install
cp .env.example .env.local   # point VITE_API_BASE at the API (default http://localhost:8000)
npm run dev                  # http://localhost:5173
```
The backend must be running (see `../backend/README.md`): `uvicorn app.main:app --reload`.

## Scripts
- `npm run dev` - dev server
- `npm run build` - typecheck + production build
- `npm run preview` - preview the build
