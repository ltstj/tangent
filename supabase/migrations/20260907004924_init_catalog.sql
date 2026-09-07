-- Tangent Phase 2 schema: catalog + synopsis embeddings.
--
-- Run this once against a fresh Supabase project (SQL Editor -> New query ->
-- paste -> Run). Idempotent, so re-running it is safe.
--
-- The embedding dimension is 384 to match all-MiniLM-L6-v2. Changing models
-- means changing this column, so it is called out rather than buried.

create extension if not exists vector;   -- pgvector: similarity search
create extension if not exists pg_trgm;  -- trigram index for as-you-type title search

create table if not exists items (
    id          text primary key,        -- "<medium>:<source>:<source_id>"
    medium      text not null check (medium in ('movie', 'tv', 'game', 'book')),
    title       text not null,
    year        integer,
    rating      real,                    -- normalized 0..10 at ingest
    popularity  real,
    overview    text not null default '',
    source      text not null default '',
    source_id   text not null default '',
    genres      text[] not null default '{}',  -- unified genre vocabulary
    tags        text[] not null default '{}',  -- canonicalized theme tags
    image       text,
    embedding   vector(384),             -- synopsis embedding; null until computed
    updated_at  timestamptz not null default now()
);

create index if not exists idx_items_medium on items (medium);

-- Genre/tag filtering ("recommend me a fantasy game") wants set containment.
create index if not exists idx_items_genres on items using gin (genres);
create index if not exists idx_items_tags   on items using gin (tags);

-- Autocomplete: trigram index makes ILIKE '%query%' fast without a full scan.
create index if not exists idx_items_title_trgm on items using gin (title gin_trgm_ops);

-- Cosine distance (<=>) is the operator the recommender's blend uses. HNSW
-- costs more to build than IVFFlat but needs no training pass and stays accurate
-- as the catalog grows, which suits a table that ingest keeps appending to.
create index if not exists idx_items_embedding on items
    using hnsw (embedding vector_cosine_ops);

-- The API connects as the owner via DATABASE_URL, so RLS does not gate it.
-- Enable it anyway: it is what stands between the public anon key and the table
-- if the frontend is ever pointed at Supabase directly.
alter table items enable row level security;

drop policy if exists "catalog is publicly readable" on items;
create policy "catalog is publicly readable"
    on items for select
    to anon, authenticated
    using (true);

-- No insert/update/delete policy: writes are ingest's job, and ingest runs
-- server-side with the service-role credentials that bypass RLS.
