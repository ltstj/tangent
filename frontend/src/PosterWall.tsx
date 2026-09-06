import { useEffect, useState } from "react";
import { getShowcase } from "./api";

// Animated background: columns of cover art slowly scrolling, dimmed behind the app.
export default function PosterWall() {
  const [posters, setPosters] = useState<string[]>([]);

  useEffect(() => {
    getShowcase(60)
      .then((items) => setPosters(items.map((i) => i.image).filter((s): s is string => !!s)))
      .catch(() => setPosters([]));
  }, []);

  if (posters.length < 8) return null;

  const colCount = 6;
  const columns: string[][] = Array.from({ length: colCount }, () => []);
  posters.forEach((src, i) => columns[i % colCount].push(src));

  return (
    <div className="wall" aria-hidden="true">
      {columns.map((col, ci) => (
        <div className={`wall-col ${ci % 2 ? "down" : "up"}`} key={ci}>
          {[...col, ...col].map((src, i) => (
            <img src={src} alt="" loading="lazy" key={i} />
          ))}
        </div>
      ))}
      <div className="wall-veil" />
    </div>
  );
}
