/**
 * Data-source credits.
 *
 * TMDB's terms require attribution for using their API, and the wording below
 * is the one they specify. IGDB, Open Library, CheapShark, IsThereAnyDeal and
 * Google Books are credited because they are doing real work here and asking
 * nothing for it. JustWatch is additionally credited inline on each offers
 * panel, which is where their data actually appears.
 *
 * Worth checking each provider's current terms before this is public — they
 * change, and this list is a good-faith rendering rather than legal advice.
 */
export default function Credits() {
  return (
    <footer className="credits">
      <p>
        This product uses the TMDB API but is not endorsed or certified by TMDB.
      </p>
      <p className="credits-sources">
        Titles and metadata from{" "}
        <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer noopener">TMDB</a>,{" "}
        <a href="https://www.igdb.com/" target="_blank" rel="noreferrer noopener">IGDB</a> and{" "}
        <a href="https://openlibrary.org/" target="_blank" rel="noreferrer noopener">Open Library</a>.
        Prices from{" "}
        <a href="https://www.cheapshark.com/" target="_blank" rel="noreferrer noopener">CheapShark</a>,{" "}
        <a href="https://isthereanydeal.com/" target="_blank" rel="noreferrer noopener">IsThereAnyDeal</a>,{" "}
        <a href="https://books.google.com/" target="_blank" rel="noreferrer noopener">Google Books</a>{" "}
        and JustWatch via TMDB.
      </p>
    </footer>
  );
}
