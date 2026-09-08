"""Record a verified subscription price.

    python -m scripts.set_subscription_price "Netflix" 15.49
    python -m scripts.set_subscription_price "Netflix" 15.49 --region US
    python -m scripts.set_subscription_price --list

The date is stamped as today, because the point of `checked_on` is "a human
looked at the provider's page on this date". Prices older than
subscriptions.STALE_AFTER_DAYS stop being served, so re-running this is how the
feature stays honest.
"""
from __future__ import annotations

import datetime as _dt
import sys

from app import subscriptions
from app.sources.tmdb import store_key
from app.store import CatalogStore


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    region = "US"
    if "--region" in sys.argv:
        region = sys.argv[sys.argv.index("--region") + 1]

    store = CatalogStore()
    rows = store.subscription_prices(region)

    if "--list" in sys.argv or not args:
        usable = subscriptions.usable_prices(rows)
        print(f"{region.upper()} — {len(usable)}/{len(rows)} usable "
              f"(stale after {subscriptions.STALE_AFTER_DAYS} days)\n")
        for r in rows:
            state = "ok  " if r["service_key"] in usable else "-   "
            price = f"${r['price']}" if r["price"] is not None else "unset"
            checked = r["checked_on"] or "never"
            print(f"  {state} {r['display_name'][:24]:26} {price:>8}  checked {checked}")
            if r["service_key"] not in usable and r["source_url"]:
                print(f"       {r['source_url']}")
        if not args:
            print('\nusage: python -m scripts.set_subscription_price "Netflix" 15.49')
        return 0

    name, raw = args[0], args[1]
    key = store_key(name)
    if not any(r["service_key"] == key for r in rows):
        print(f"'{name}' (key '{key}') is not in the table for {region.upper()}.")
        print("Known:", ", ".join(r["display_name"] for r in rows))
        return 1

    price = None if raw.lower() in ("none", "null", "unset") else float(raw)
    ok = store.set_subscription_price(key, price, region=region, checked_on=_dt.date.today())
    print(f"{'set' if ok else 'FAILED'}: {name} = "
          f"{'unset' if price is None else f'${price:.2f}'} "
          f"(checked {_dt.date.today()}, region {region.upper()})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
