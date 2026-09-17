import { useEffect, useState } from "react";

import {
  fetchWatchLater,
  moveWatchLaterToLibrary,
  removeTitleFromWatchLater,
} from "../api";
import { ExternalIcon } from "../icons";
import type { RecommendationSeed, WatchLaterItem } from "../types";


interface Props {
  onCountChange: (count: number) => void;
  onFindSimilar: (seeds: RecommendationSeed[]) => void;
}


export function WatchLaterScreen({ onCountChange, onFindSimilar }: Props) {
  const [items, setItems] = useState<WatchLaterItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [moving, setMoving] = useState<{ id: number; watched: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchWatchLater()
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        onCountChange(response.total);
        setError(null);
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [onCountChange]);

  async function remove(item: WatchLaterItem) {
    setRemovingId(item.id);
    try {
      await removeTitleFromWatchLater(item.id);
      setItems((current) => {
        const next = current.filter((candidate) => candidate.id !== item.id);
        onCountChange(next.length);
        return next;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update Watch Later");
    } finally {
      setRemovingId(null);
    }
  }

  async function moveToLibrary(item: WatchLaterItem, watched: boolean) {
    setMoving({ id: item.id, watched });
    setError(null);
    try {
      await moveWatchLaterToLibrary(item.id, watched);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
      onCountChange(Math.max(0, items.length - 1));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not move title to Library");
    } finally {
      setMoving(null);
    }
  }

  return (
    <main className="watch-later-screen">
      <header className="watch-later-header">
        <div>
          <span>Personal queue</span>
          <h1>Watch later</h1>
          <p>
            Stored permanently on this device. Finish a title here when you
            want to file it back into your library.
          </p>
        </div>
        <strong>{items.length}</strong>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      {loading ? (
        <div className="watch-later-empty">Loading your queue…</div>
      ) : items.length ? (
        <section className="watch-later-grid" aria-label="Watch Later titles">
          {items.map((item) => (
            <article className="watch-later-card" key={item.id}>
              {item.poster_url ? (
                <img src={item.poster_url} alt="" loading="lazy" />
              ) : (
                <div className={`poster-fallback cover-${item.id % 6}`}>
                  {item.title.slice(0, 1)}
                </div>
              )}
              <div>
                <span className="watch-later-kind">
                  {item.media_type === "tv" ? "TV show" : "Movie"}
                  {item.start_year ? ` · ${item.start_year}` : ""}
                  {" · In library"}
                </span>
                <h2>{item.title}</h2>
                <p>
                  {item.genres.slice(0, 2).join(" · ") || "Genre pending"}
                </p>
                <div className="watch-later-ratings">
                  <span>IMDb {item.imdb_rating?.toFixed(1) ?? "—"}</span>
                  <span>
                    RT{" "}
                    {item.rotten_tomatoes_rating != null
                      ? `${Math.round(item.rotten_tomatoes_rating)}%`
                      : "—"}
                  </span>
                </div>
                <div className="watch-later-actions">
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => moveToLibrary(item, true)}
                    disabled={moving?.id === item.id || removingId === item.id}
                  >
                    {moving?.id === item.id && moving.watched
                      ? "Moving…"
                      : "Watched → Library"}
                  </button>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => moveToLibrary(item, false)}
                    disabled={moving?.id === item.id || removingId === item.id}
                  >
                    {moving?.id === item.id && !moving.watched
                      ? "Moving…"
                      : "Move to Library"}
                  </button>
                  <button
                    className="text-button"
                    type="button"
                    onClick={() =>
                      onFindSimilar([
                        {
                          id: item.id,
                          title: item.title,
                          media_type: item.media_type,
                          year: item.start_year,
                        },
                      ])
                    }
                  >
                    Find similar tonight
                  </button>
                  {item.imdb_id ? (
                    <a
                      className="text-button"
                      href={`https://www.imdb.com/title/${item.imdb_id}/`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      IMDb <ExternalIcon />
                    </a>
                  ) : null}
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => remove(item)}
                    disabled={removingId === item.id || moving?.id === item.id}
                  >
                    {removingId === item.id ? "Removing…" : "Remove"}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <div className="watch-later-empty">
          <h2>Your Watch Later queue is empty.</h2>
          <p>Add titles from your library or from a Tonight recommendation.</p>
        </div>
      )}
    </main>
  );
}
