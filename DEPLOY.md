# Deploying Tangent

Two pieces: the API on **Fly.io** and the static frontend on **Cloudflare Pages**.
The database is already Supabase and does not move.

Nothing here is automated, because each step needs an account only you can create.
The config files are committed and tested; these are the buttons.

---

## Before you start

Decide the email-confirmation question, because it changes whether strangers can
actually sign up:

- **Confirmation on** (current setting) — Supabase's built-in mailer allows only
  a few messages an hour, so real signups will fail silently. You need SMTP
  configured under **Authentication → Emails** for this to work in public.
- **Confirmation off** — anyone can register with an unverified address. Fine for
  showing friends, wrong for anything real.

---

## 1. The API on Fly.io

From `backend/`:

```bash
fly auth signup          # or: fly auth login
fly launch --no-deploy   # detects fly.toml; say no to adding a database
```

`fly launch` may want to rename the app if `tangent-api` is taken. Let it, then
note the name it chose — the frontend needs the resulting URL.

### Secrets

These are set as Fly secrets rather than in `fly.toml`, so they are never in git:

```bash
fly secrets set \
  DATABASE_URL='...' \
  SUPABASE_URL='...' \
  SUPABASE_ANON_KEY='...' \
  SUPABASE_SERVICE_ROLE_KEY='...' \
  TMDB_API_KEY='...' \
  IGDB_CLIENT_ID='...' \
  IGDB_CLIENT_SECRET='...' \
  GOOGLE_BOOKS_API_KEY='...' \
  ITAD_API_KEY='...'
```

Copy the values from `backend/.env`. Use single quotes — the database password
and several keys contain characters a shell would otherwise interpret.

`CORS_ORIGINS` is set in step 3, once the frontend has a URL.

### Deploy

```bash
fly deploy
fly logs          # watch the first boot
curl https://<your-app>.fly.dev/ready
```

`/ready` should report the catalog size, `"supabase": true`, and full embedding
coverage. If `"supabase"` is false, a secret is missing or misspelled.

### Notes

- `fly.toml` uses `auto_stop_machines = 'suspend'`, so an idle machine suspends
  and resumes in well under a second. Set `min_machines_running = 1` to remove
  even that, at the cost of an always-on machine.
- Region is `iad` to sit beside Supabase in `us-east-1`. Every request touches
  Postgres, so moving the API further away shows up directly in response times.
- The image has no embedding stack. `scripts/build_embeddings.py` stays a local
  task run against the same database — see `requirements-embed.txt`.

---

## 2. The frontend on Cloudflare Pages

Create a project at **dash.cloudflare.com → Workers & Pages → Create → Pages →
Connect to Git**, pick `ltstj/tangent`, then:

| Setting | Value |
|---|---|
| Framework preset | None (or Vite) |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Output directory | `dist` |

### Environment variables

Set these for **Production** (and Preview, if you use preview branches):

```
VITE_API_BASE          https://<your-app>.fly.dev
VITE_SUPABASE_URL      https://<project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY <publishable key>
```

All three are safe in a browser bundle: the URLs are public and the publishable
key identifies the project, not a person. **Never** put the service-role key
here — it bypasses row-level security.

`VITE_API_BASE` is required. A production build without it fails loudly at load
rather than silently pointing every visitor's browser at their own machine.

---

## 3. Point the two at each other

Back in `backend/`, once Pages has given you a URL:

```bash
fly secrets set CORS_ORIGINS='https://<your-project>.pages.dev'
```

Add your custom domain to that list too if you attach one, comma-separated. The
API rejects browser requests from origins not on this list — a deploy still
allowing `localhost` while `APP_ENV=production` logs a warning on boot, because
a silent CORS failure in someone else's browser is miserable to debug.

---

## 4. Check it actually works

Open the Pages URL and walk through:

1. Search a title — the dropdown should populate
2. Get recommendations
3. Expand **Where to get it** on a game and on a book
4. Sign up, mark something, open **My library**
5. Get recommendations with nothing typed — should say "Shaped by your library"

If searches work but offers are empty, a data-source key is missing on Fly. If
nothing loads at all, check the browser console for a CORS error, which means
step 3 is wrong.

---

## Ongoing

- **Supabase free tier pauses a project after ~7 days idle.** A shared link goes
  dead until you un-pause it from the dashboard.
- **Subscription prices expire after 120 days** by design, then stop being
  served rather than going quietly stale. Re-check them with
  `python -m scripts.set_subscription_price --list`.
- **Rate limits are per-process.** Fly running more than one machine multiplies
  the effective limit; it would want a shared store at that point.
- **New titles need embedding.** Anything promoted into the catalog after the
  last run is unembedded until `python -m scripts.build_embeddings` is run
  locally against the same database.
