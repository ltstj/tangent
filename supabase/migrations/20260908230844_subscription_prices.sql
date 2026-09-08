-- Subscription prices, for "the cheapest subscription that already has it".
--
-- TMDB tells us which services carry a title but publishes no prices at all
-- (provider objects have four keys, none of them a price), so this table is the
-- price half and it is ours to maintain.
--
-- The design point: a database does not make data fresh, it only makes it
-- editable. Something still has to put correct numbers in. So `checked_on` is
-- part of the record, not an afterthought, and the API refuses to serve a price
-- older than its cutoff - going stale fails visibly instead of quietly showing
-- last year's price as this year's.
--
-- `price` starts NULL on purpose. An unverified number in a field whose whole
-- job is accuracy is worse than no number: with NULL the app behaves exactly as
-- it does without this table, and starts helping the moment a real price is
-- entered. Fill them in with:
--     python -m scripts.set_subscription_price "Netflix" 15.49

create table if not exists subscription_prices (
    service_key   text not null,            -- normalized name; see tmdb.store_key()
    display_name  text not null,
    region        char(2) not null default 'US',
    price         numeric(6,2),             -- NULL = we do not know, and won't pretend
    currency      text not null default 'USD',
    period        text not null default 'month',
    checked_on    date,                     -- NULL = never verified
    source_url    text,                     -- the provider's own pricing page
    note          text not null default '',
    primary key (service_key, region)
);

comment on column subscription_prices.checked_on is
    'Date a human last confirmed this price against source_url. Prices older '
    'than the app''s staleness cutoff are not served.';

insert into subscription_prices
    (service_key, display_name, region, price, currency, period, checked_on, source_url)
values
    ('netflix', 'Netflix', 'US', NULL, 'USD', 'month', NULL, 'https://help.netflix.com/en/node/24926'),
    ('hulu', 'Hulu', 'US', NULL, 'USD', 'month', NULL, 'https://www.hulu.com/plans'),
    ('hbo max', 'HBO Max', 'US', NULL, 'USD', 'month', NULL, 'https://www.max.com/plans'),
    ('disney plus', 'Disney Plus', 'US', NULL, 'USD', 'month', NULL, 'https://www.disneyplus.com/welcome'),
    ('amazon prime video', 'Amazon Prime Video', 'US', NULL, 'USD', 'month', NULL, 'https://www.amazon.com/gp/video/offers'),
    ('paramount plus', 'Paramount Plus', 'US', NULL, 'USD', 'month', NULL, 'https://www.paramountplus.com/account/signup/pickplan/'),
    ('peacock premium', 'Peacock Premium', 'US', NULL, 'USD', 'month', NULL, 'https://www.peacocktv.com/plans'),
    ('apple tv plus', 'Apple TV+', 'US', NULL, 'USD', 'month', NULL, 'https://tv.apple.com'),
    ('starz', 'Starz', 'US', NULL, 'USD', 'month', NULL, 'https://www.starz.com/us/en/pricing'),
    ('amc plus', 'AMC+', 'US', NULL, 'USD', 'month', NULL, 'https://www.amcplus.com'),
    ('crunchyroll', 'Crunchyroll', 'US', NULL, 'USD', 'month', NULL, 'https://www.crunchyroll.com/premium')
on conflict (service_key, region) do nothing;

alter table subscription_prices enable row level security;

drop policy if exists "subscription prices are publicly readable" on subscription_prices;
create policy "subscription prices are publicly readable"
    on subscription_prices for select
    to anon, authenticated
    using (true);
