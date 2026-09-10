-- Was this recommendation a good match?
--
-- Distinct from the rating in `library`, and the distinction is the point:
-- "I liked this show" is a verdict on a title, while "this was a good answer to
-- 'give me something like Blade Runner'" is a verdict on the *pairing*. Only the
-- second can tell us whether the scoring weights are right - W_EMBED = 0.9 and
-- W_TAG = 0.6 currently rest on hand sweeps against a handful of seed cases.
--
-- `source_ids` records what produced the recommendation, which is what makes a
-- row interpretable later: without it you know someone disliked a suggestion but
-- not what it was a suggestion *for*.

create table if not exists match_feedback (
    user_id    uuid not null references auth.users(id) on delete cascade,
    item_id    text not null references items(id) on delete cascade,
    -- The favorites and/or genres the recommendation came from. Plain text so a
-- genre seed ("g:fantasy") and a catalog id can share the column.
    source_ids text[] not null default '{}',
    helpful    boolean not null,
    created_at timestamptz not null default now(),
    primary key (user_id, item_id)
);

create index if not exists idx_match_feedback_user on match_feedback (user_id);
-- For the eventual question "which pairings does everyone reject?", which is
-- what would let weights be fitted instead of guessed.
create index if not exists idx_match_feedback_item on match_feedback (item_id, helpful);

alter table match_feedback enable row level security;

drop policy if exists "own feedback is readable" on match_feedback;
create policy "own feedback is readable"
    on match_feedback for select to authenticated
    using (auth.uid() = user_id);

drop policy if exists "own feedback is writable" on match_feedback;
create policy "own feedback is writable"
    on match_feedback for insert to authenticated
    with check (auth.uid() = user_id);

drop policy if exists "own feedback is updatable" on match_feedback;
create policy "own feedback is updatable"
    on match_feedback for update to authenticated
    using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own feedback is deletable" on match_feedback;
create policy "own feedback is deletable"
    on match_feedback for delete to authenticated
    using (auth.uid() = user_id);
