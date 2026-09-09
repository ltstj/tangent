import { useState } from "react";
import { getOffers, type CatalogItem, type Offer, type OffersResponse } from "./api";

const KIND_LABEL: Record<Offer["kind"], string> = {
  subscription: "Stream",
  free: "Free",
  rent: "Rent",
  buy: "Buy",
  link: "Find it",
};

function money(o: Offer): string | null {
  return o.price === null ? null : `$${o.price.toFixed(2)}`;
}

/**
 * "Where to get it" for one title, fetched on demand.
 *
 * Lazy on purpose: a page of twelve results would otherwise fire twelve
 * requests that each hit CheapShark or TMDB, for cards the reader may never
 * look at.
 */
export default function Offers({ item }: { item: CatalogItem }) {
  const [data, setData] = useState<OffersResponse | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [open, setOpen] = useState(false);

  async function toggle() {
    if (open) return setOpen(false);
    setOpen(true);
    if (data || state === "loading") return;
    setState("loading");
    try {
      setData(await getOffers(item.id));
      setState("idle");
    } catch {
      setState("error");
    }
  }

  return (
    <div className="offers">
      <button className="offers-toggle" onClick={toggle} aria-expanded={open}>
        {open ? "▾" : "▸"} Where to get it
      </button>

      {open && state === "loading" && <p className="offers-msg">Checking prices…</p>}
      {open && state === "error" && <p className="offers-msg">Couldn’t load prices.</p>}

      {open && data && state === "idle" && (
        <>
          {data.cheapest_subscription && (
            <p className="offers-best">
              Cheapest subscription: <strong>{data.cheapest_subscription.store}</strong>{" "}
              ${data.cheapest_subscription.price.toFixed(2)}/mo
            </p>
          )}

          {/* Never collapse "nothing available" into "we couldn't check". */}
          {data.offers.length === 0 ? (
            <p className={`offers-msg${data.status === "source_unavailable" ? " offers-warn" : ""}`}>
              {data.status === "source_unavailable"
                ? `Couldn't reach the price source. ${data.detail}`
                : data.detail || "Nothing listed."}
            </p>
          ) : (
            <ul className="offer-list">
              {data.offers.map((o, i) => (
                <li key={`${o.kind}-${o.store}-${i}`}>
                  <span className={`okind okind-${o.kind}`}>{KIND_LABEL[o.kind]}</span>
                  <a className="ostore" href={o.url} target="_blank" rel="noreferrer noopener">
                    {o.store}
                  </a>
                  {/* A missing price is stated, never implied as free. */}
                  {money(o) ? (
                    <span className="oprice">
                      {money(o)}
                      {o.was !== null && o.was > (o.price ?? 0) && (
                        <span className="owas">${o.was.toFixed(2)}</span>
                      )}
                    </span>
                  ) : (
                    <span className="oprice oprice-unknown">—</span>
                  )}
                  {o.note && <span className="onote">{o.note}</span>}
                </li>
              ))}
            </ul>
          )}

          {data.notes.length > 0 && (
            <ul className="offer-notes">
              {data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}

          {/* The requested region and the region the prices apply to can differ
              (CheapShark is US-only), so say which you are looking at. */}
          {data.price_region && data.price_region !== data.region && (
            <p className="offers-attr">Prices shown for {data.price_region}.</p>
          )}

          {data.attribution && <p className="offers-attr">{data.attribution}</p>}
        </>
      )}
    </div>
  );
}
