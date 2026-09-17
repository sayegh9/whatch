import { useEffect, useState } from "react";
import { CloseIcon, ExternalIcon, LinkIcon } from "../icons";
import type { TitleDetail } from "../types";

interface Props {
  detail: TitleDetail | null;
  loading: boolean;
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onRefresh: () => Promise<void>;
  onToggleWatchLater: () => Promise<void>;
}

function displayYear(detail: TitleDetail) {
  if (!detail.start_year) return "Year unknown";
  if (detail.is_ongoing) return `${detail.start_year}–`;
  if (detail.end_year) return `${detail.start_year}–${detail.end_year}`;
  return detail.start_year;
}

export function DetailDrawer({
  detail,
  loading,
  onClose,
  onSave,
  onRefresh,
  onToggleWatchLater,
}: Props) {
  const [status, setStatus] = useState("want_to_watch");
  const [priority, setPriority] = useState("normal");
  const [rating, setRating] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [editingMetadata, setEditingMetadata] = useState(false);
  const [title, setTitle] = useState("");
  const [mediaType, setMediaType] = useState<"movie" | "tv">("movie");
  const [startYear, setStartYear] = useState("");
  const [endYear, setEndYear] = useState("");
  const [runtime, setRuntime] = useState("");
  const [releaseDate, setReleaseDate] = useState("");
  const [genres, setGenres] = useState("");
  const [overview, setOverview] = useState("");
  const [posterUrl, setPosterUrl] = useState("");
  const [imdbRating, setImdbRating] = useState("");
  const [rtRating, setRtRating] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [watchLaterBusy, setWatchLaterBusy] = useState(false);

  useEffect(() => {
    if (!detail) return;
    setStatus(detail.status);
    setPriority(detail.priority);
    setRating(detail.user_rating?.toString() ?? "");
    setNotes(detail.notes ?? "");
    setTags(detail.tags.join(", "));
    setTitle(detail.title);
    setMediaType(detail.media_type);
    setStartYear(detail.start_year?.toString() ?? "");
    setEndYear(detail.end_year?.toString() ?? "");
    setRuntime(detail.runtime_minutes?.toString() ?? "");
    setReleaseDate(detail.release_date ?? "");
    setGenres(detail.genres.join(", "));
    setOverview(detail.overview ?? "");
    setPosterUrl(detail.poster_url ?? "");
    setImdbRating(detail.imdb_rating?.toString() ?? "");
    setRtRating(detail.rotten_tomatoes_rating?.toString() ?? "");
    setEditingMetadata(false);
  }, [detail]);

  if (!detail && !loading) return null;

  async function save() {
    if (!detail) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        status,
        priority,
        user_rating: rating ? Number(rating) : null,
        notes: notes || null,
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      };
      if (editingMetadata) {
        const correctedGenres = genres.split(",").map((genre) => genre.trim()).filter(Boolean);
        const correctedValues: Record<string, unknown> = {
          title: title.trim(),
          media_type: mediaType,
          start_year: startYear ? Number(startYear) : null,
          end_year: endYear ? Number(endYear) : null,
          runtime_minutes: runtime ? Number(runtime) : null,
          release_date: releaseDate || null,
          genres: correctedGenres,
          overview: overview || null,
          poster_url: posterUrl || null,
          imdb_rating: imdbRating ? Number(imdbRating) : null,
          rotten_tomatoes_rating: rtRating ? Number(rtRating) : null,
        };
        const currentValues: Record<string, unknown> = {
          title: detail.title,
          media_type: detail.media_type,
          start_year: detail.start_year,
          end_year: detail.end_year,
          runtime_minutes: detail.runtime_minutes,
          release_date: detail.release_date,
          genres: detail.genres,
          overview: detail.overview,
          poster_url: detail.poster_url,
          imdb_rating: detail.imdb_rating,
          rotten_tomatoes_rating: detail.rotten_tomatoes_rating,
        };
        for (const [field, value] of Object.entries(correctedValues)) {
          if (JSON.stringify(value) !== JSON.stringify(currentValues[field])) payload[field] = value;
        }
      }
      await onSave(payload);
      setEditingMetadata(false);
    } finally {
      setSaving(false);
    }
  }

  async function refreshMetadata() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await onRefresh();
    } catch (reason) {
      setRefreshError(reason instanceof Error ? reason.message : "Metadata refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function toggleWatchLater() {
    setWatchLaterBusy(true);
    try {
      await onToggleWatchLater();
    } finally {
      setWatchLaterBusy(false);
    }
  }

  return (
    <aside className="detail-drawer" aria-label="Title details">
      {loading || !detail ? (
        <div className="drawer-loading">Loading title…</div>
      ) : (
        <>
          <div className="drawer-scroll">
            <button className="icon-button drawer-close" onClick={onClose} aria-label="Close">
              <CloseIcon />
            </button>
            <h2>{detail.title}</h2>
            <div className="detail-identity">
              {detail.poster_url ? (
                <img className="drawer-poster" src={detail.poster_url} alt="" />
              ) : (
                <span className={`drawer-monogram cover-${detail.id % 6}`}>
                  {detail.title.slice(0, 1)}
                </span>
              )}
              <div>
                <p>{detail.media_type === "tv" ? "TV show" : "Movie"} · {displayYear(detail)}</p>
                <div className="rating-line">
                  <span>IMDb</span>
                  <strong>{detail.imdb_rating?.toFixed(1) ?? "N/A"}</strong>
                  <span>RT</span>
                  <strong>
                    {detail.rotten_tomatoes_rating != null
                      ? `${Math.round(detail.rotten_tomatoes_rating)}%`
                      : "N/A"}
                  </strong>
                </div>
              </div>
            </div>
            <div className="metadata-strip">
              <span>{detail.runtime_minutes ? `${detail.runtime_minutes} min` : "Runtime unknown"}</span>
              <span>{detail.genres.length ? detail.genres.join(" · ") : "Genres pending"}</span>
            </div>
            {detail.overview ? <p className="detail-overview">{detail.overview}</p> : null}
            <div className="metadata-refresh">
              <div>
                <strong>Metadata: {detail.metadata_status}</strong>
                <small>
                  {detail.metadata_refreshed_at
                    ? `Updated ${new Date(detail.metadata_refreshed_at).toLocaleDateString()}`
                    : "Not refreshed yet"}
                </small>
              </div>
              <button
                className="text-button"
                onClick={refreshMetadata}
                disabled={refreshing || !detail.imdb_id}
              >
                {refreshing ? "Refreshing…" : "Refresh"}
              </button>
            </div>
            {refreshError ? <div className="inline-error">{refreshError}</div> : null}
            <section className="metadata-editor">
              <div className="section-heading">
                <div>
                  <h3>Catalog metadata</h3>
                  <small>{detail.manual_fields.length ? `${detail.manual_fields.length} protected correction${detail.manual_fields.length === 1 ? "" : "s"}` : "Provider-managed"}</small>
                </div>
                <button className="text-button" type="button" onClick={() => setEditingMetadata((current) => !current)}>
                  {editingMetadata ? "Cancel editing" : "Correct metadata"}
                </button>
              </div>
              {editingMetadata ? (
                <div className="metadata-editor-fields">
                  <label className="field"><span>Title</span><input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
                  <div className="field-row">
                    <label><span>Type</span><select value={mediaType} onChange={(event) => setMediaType(event.target.value as "movie" | "tv")}><option value="movie">Movie</option><option value="tv">TV show</option></select></label>
                    <label><span>Release date</span><input type="date" value={releaseDate} onChange={(event) => setReleaseDate(event.target.value)} /></label>
                  </div>
                  <div className="field-row metadata-number-row">
                    <label><span>Start year</span><input type="number" min="1870" max="2200" value={startYear} onChange={(event) => setStartYear(event.target.value)} /></label>
                    <label><span>End year</span><input type="number" min="1870" max="2200" value={endYear} onChange={(event) => setEndYear(event.target.value)} /></label>
                    <label><span>Runtime</span><input type="number" min="1" max="1440" value={runtime} onChange={(event) => setRuntime(event.target.value)} /></label>
                  </div>
                  <label className="field"><span>Genres</span><input value={genres} onChange={(event) => setGenres(event.target.value)} placeholder="Drama, Mystery" /><small>Separate genres with commas.</small></label>
                  <div className="field-row">
                    <label><span>IMDb rating</span><input type="number" min="0" max="10" step="0.1" value={imdbRating} onChange={(event) => setImdbRating(event.target.value)} /></label>
                    <label><span>RT rating</span><input type="number" min="0" max="100" step="1" value={rtRating} onChange={(event) => setRtRating(event.target.value)} /></label>
                  </div>
                  <label className="field"><span>Poster URL</span><input type="url" value={posterUrl} onChange={(event) => setPosterUrl(event.target.value)} placeholder="https://…" /></label>
                  <label className="field"><span>Overview</span><textarea value={overview} onChange={(event) => setOverview(event.target.value)} maxLength={20000} /></label>
                  <p>Saved corrections are protected from future provider refreshes.</p>
                </div>
              ) : null}
            </section>
            <div className="field-row">
              <label>
                <span>Status</span>
                <select value={status} onChange={(event) => setStatus(event.target.value)}>
                  <option value="want_to_watch">Want to watch</option>
                  <option value="watching">Watching</option>
                  <option value="watched">Watched</option>
                  <option value="dropped">Dropped</option>
                  <option value="maybe_later">Maybe later</option>
                  <option value="hidden">Hidden</option>
                </select>
              </label>
              <label>
                <span>Priority</span>
                <select value={priority} onChange={(event) => setPriority(event.target.value)}>
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                </select>
              </label>
            </div>
            <label className="field">
              <span>Your rating</span>
              <input
                type="number"
                min="0"
                max="10"
                step="0.5"
                value={rating}
                placeholder="Not rated"
                onChange={(event) => setRating(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Notes</span>
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                maxLength={10000}
                placeholder="Add a private note…"
              />
            </label>
            <label className="field">
              <span>Tags</span>
              <input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="cerebral, slow-burn, favorite"
              />
              <small>Separate tags with commas.</small>
            </label>
            <section className="sources">
              <div className="section-heading">
                <h3>Sources ({detail.links.length})</h3>
              </div>
              {detail.links.map((link) => (
                <a
                  key={link.id}
                  className="source-link"
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <LinkIcon />
                  <span>
                    <strong>{link.domain}</strong>
                    <small>{link.url}</small>
                  </span>
                  <ExternalIcon />
                </a>
              ))}
            </section>
          </div>
          <div className="drawer-actions">
            <button
              className="secondary-button"
              type="button"
              onClick={toggleWatchLater}
              disabled={watchLaterBusy}
            >
              {watchLaterBusy
                ? "Updating…"
                : detail.watch_later
                  ? "Remove from Watch Later"
                  : "Add to Watch Later"}
            </button>
            {detail.imdb_id ? (
              <a
                className="secondary-button"
                href={`https://www.imdb.com/title/${detail.imdb_id}/`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open IMDb
                <ExternalIcon />
              </a>
            ) : null}
            <button className="primary-button" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
