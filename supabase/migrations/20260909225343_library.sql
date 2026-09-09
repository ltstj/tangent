-- Phase 4: per-user library.
--
-- One row per (user, title): what they mean to do with it, and what they
-- thought of it afterwards. This is the first table in the project that holds
-- personal data, so two things are deliberate:
--
-- 1. `on delete cascade` from auth.users. "Delete my data" then becomes a real
--    guarantee enforced by the database rather than a promise made by
--    application code that might miss a table.
-- 2. RLS restricts every operation to auth.uid() = user_id. Note this is
--    defence in depth, NOT the primary guard: the API connects as the table
--    owner over DATABASE_URL and therefore bypasses RLS, so it must filter by
--    user id itself. RLS is what stops a leak if anything ever talks to this
--    table with an end-user's key.

do $$ begin
    create type library_status as enum ('want', 'in_progress', 'finished');
exception
    when duplicate_object then null;
end $$;

create table if not exists library (
    user_id    uuid not null references auth.users(id) on delete cascade,
    item_id    text not null references items(id) on delete cascade,
    status     library_status not null default 'want',
    -- Same 0..10 scale the catalog's own ratings use, so the two are comparable.
    rating     numeric(3,1) check (rating >= 0 and rating <= 10),
    note       text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (user_id, item_id)
);

-- Every read is "this user's library", so the user column leads.
create index if not exists idx_library_user on library (user_id, updated_at desc);
create index if not exists idx_library_item on library (item_id);

alter table library enable row level security;

drop policy if exists "own library is readable" on library;
create policy "own library is readable"
    on library for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "own library is insertable" on library;
create policy "own library is insertable"
    on library for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists "own library is updatable" on library;
create policy "own library is updatable"
    on library for update to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "own library is deletable" on library;
create policy "own library is deletable"
    on library for delete to authenticated
    using (auth.uid() = user_id);
