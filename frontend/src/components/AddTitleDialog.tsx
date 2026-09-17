import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { commitTitleIntake, resolveTitleIntake } from "../api";
import { CloseIcon, SearchIcon } from "../icons";
import type {
  IntakeCandidate,
  IntakeResolveResponse,
  TitleDetail,
} from "../types";


type Destination = "library" | "watch_later";
type IntakeMode = "single" | "bulk";

interface Props {
  onClose: () => void;
  onAdded: (items: TitleDetail[], destination: Destination) => void;
}

interface BulkRow {
  input: string;
  resolution: IntakeResolveResponse | null;
  selectedKey: string | null;
  error: string | null;
}

const MAX_BULK_TITLES = 25;

function candidateKey(candidate: IntakeCandidate) {
  return `${candidate.media_type}:${candidate.tmdb_id}`;
}

function isUrl(value: string) {
  return /^https?:\/\//i.test(value.trim());
}

function defaultCandidateKey(response: IntakeResolveResponse) {
  return response.candidates[0] ? candidateKey(response.candidates[0]) : null;
}

export function AddTitleDialog({ onClose, onAdded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const searchVersion = useRef(0);
  const [mode, setMode] = useState<IntakeMode>("single");
  const [input, setInput] = useState("");
  const [bulkInput, setBulkInput] = useState("");
  const [bulkRows, setBulkRows] = useState<BulkRow[]>([]);
  const [mediaType, setMediaType] = useState<"either" | "movie" | "tv">("either");
  const [destination, setDestination] = useState<Destination>("library");
  const [resolution, setResolution] = useState<IntakeResolveResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitProgress, setCommitProgress] = useState("");
  const [error, setError] = useState<string | null>(null);

  const selectedCandidate = useMemo(
    () => resolution?.candidates.find((candidate) => candidateKey(candidate) === selectedKey) ?? null,
    [resolution, selectedKey],
  );

  const selectedBulkRows = useMemo(
    () => bulkRows.flatMap((row) => {
      const candidate = row.resolution?.candidates.find(
        (option) => candidateKey(option) === row.selectedKey,
      );
      return candidate ? [{ row, candidate }] : [];
    }),
    [bulkRows],
  );

  useEffect(() => {
    inputRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !committing) onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [committing, onClose]);

  useEffect(() => {
    const query = input.trim();
    if (mode !== "single" || query.length < 3 || isUrl(query)) {
      setSuggesting(false);
      return;
    }
    const version = ++searchVersion.current;
    const timer = window.setTimeout(async () => {
      setSuggesting(true);
      setError(null);
      try {
        const response = await resolveTitleIntake({ input: query, media_type: mediaType });
        if (version !== searchVersion.current) return;
        setResolution(response);
        setSelectedKey(
          response.exact || response.candidates.length === 1
            ? defaultCandidateKey(response)
            : null,
        );
      } catch (reason) {
        if (version === searchVersion.current) {
          setError(reason instanceof Error ? reason.message : "Could not find this title");
        }
      } finally {
        if (version === searchVersion.current) setSuggesting(false);
      }
    }, 450);
    return () => window.clearTimeout(timer);
  }, [input, mediaType, mode]);

  async function resolve(event: FormEvent) {
    event.preventDefault();
    if (!input.trim() || searching) return;
    const version = ++searchVersion.current;
    setSearching(true);
    setSuggesting(false);
    setError(null);
    try {
      const response = await resolveTitleIntake({
        input: input.trim(),
        media_type: mediaType,
      });
      if (version !== searchVersion.current) return;
      setResolution(response);
      setSelectedKey(
        response.exact || response.candidates.length === 1
          ? defaultCandidateKey(response)
          : null,
      );
    } catch (reason) {
      if (version === searchVersion.current) {
        setError(reason instanceof Error ? reason.message : "Could not find this title");
      }
    } finally {
      if (version === searchVersion.current) setSearching(false);
    }
  }

  async function previewBulk() {
    const inputs = [...new Set(
      bulkInput.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    )];
    if (!inputs.length || searching) return;
    if (inputs.length > MAX_BULK_TITLES) {
      setError(`Bulk add supports up to ${MAX_BULK_TITLES} titles at a time.`);
      return;
    }
    setSearching(true);
    setError(null);
    const results = await Promise.all(inputs.map(async (value): Promise<BulkRow> => {
      try {
        const response = await resolveTitleIntake({ input: value, media_type: mediaType });
        return {
          input: value,
          resolution: response,
          selectedKey: defaultCandidateKey(response),
          error: null,
        };
      } catch (reason) {
        return {
          input: value,
          resolution: null,
          selectedKey: null,
          error: reason instanceof Error ? reason.message : "No match found",
        };
      }
    }));
    setBulkRows(results);
    setSearching(false);
  }

  async function addSelected() {
    if (!selectedCandidate || committing) return;
    setCommitting(true);
    setError(null);
    try {
      const response = await commitTitleIntake({
        tmdb_id: selectedCandidate.tmdb_id,
        media_type: selectedCandidate.media_type,
        destination,
        source_url: resolution?.source_url ?? undefined,
      });
      onAdded([response.item], destination);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add this title");
    } finally {
      setCommitting(false);
    }
  }

  async function addBulk() {
    if (!selectedBulkRows.length || committing) return;
    setCommitting(true);
    setError(null);
    const added: TitleDetail[] = [];
    try {
      for (let index = 0; index < selectedBulkRows.length; index += 1) {
        const { row, candidate } = selectedBulkRows[index];
        setCommitProgress(`${index + 1} of ${selectedBulkRows.length}`);
        const response = await commitTitleIntake({
          tmdb_id: candidate.tmdb_id,
          media_type: candidate.media_type,
          destination,
          source_url: row.resolution?.source_url ?? undefined,
        });
        added.push(response.item);
      }
      onAdded(added, destination);
    } catch (reason) {
      setError(
        `${added.length} added before the import stopped. ${
          reason instanceof Error ? reason.message : "Could not add the remaining titles"
        }`,
      );
    } finally {
      setCommitProgress("");
      setCommitting(false);
    }
  }

  function switchMode(nextMode: IntakeMode) {
    searchVersion.current += 1;
    setMode(nextMode);
    setSearching(false);
    setSuggesting(false);
    setError(null);
    setResolution(null);
    setSelectedKey(null);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className="add-title-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="add-title-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-title-heading"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="add-title-header">
          <div>
            <span>Catalog intake</span>
            <h1 id="add-title-heading">Add titles</h1>
            <p>Search as you type, paste a provider link, or add a list in one pass.</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close add title">
            <CloseIcon />
          </button>
        </header>

        <div className="add-title-mode" role="group" aria-label="Intake mode">
          <button type="button" className={mode === "single" ? "is-active" : ""} aria-pressed={mode === "single"} onClick={() => switchMode("single")}>Single title</button>
          <button type="button" className={mode === "bulk" ? "is-active" : ""} aria-pressed={mode === "bulk"} onClick={() => switchMode("bulk")}>Bulk add</button>
        </div>

        {mode === "single" ? (
          <form className="add-title-search" onSubmit={resolve}>
            <label>
              <span className="sr-only">Movie name or link</span>
              <SearchIcon />
              <input
                ref={inputRef}
                value={input}
                onChange={(event) => {
                  searchVersion.current += 1;
                  setInput(event.target.value);
                  setSearching(false);
                  setSuggesting(false);
                  setResolution(null);
                  setSelectedKey(null);
                  setError(null);
                }}
                placeholder="Movie name or IMDb, TMDB, RT link…"
                aria-label="Movie name or link"
                maxLength={2000}
              />
            </label>
            <select value={mediaType} onChange={(event) => {
              searchVersion.current += 1;
              setMediaType(event.target.value as typeof mediaType);
              setSearching(false);
              setSuggesting(false);
              setResolution(null);
              setSelectedKey(null);
            }} aria-label="Title type">
              <option value="either">Movie or TV</option>
              <option value="movie">Movie</option>
              <option value="tv">TV show</option>
            </select>
            <button className="primary-button" type="submit" disabled={!input.trim() || searching}>
              {searching ? "Finding…" : "Find title"}
            </button>
          </form>
        ) : (
          <div className="bulk-intake-input">
            <label>
              <span>One title or direct provider link per line</span>
              <textarea
                value={bulkInput}
                onChange={(event) => {
                  setBulkInput(event.target.value);
                  setBulkRows([]);
                  setError(null);
                }}
                placeholder={"Perfect Days\nhttps://www.imdb.com/title/tt0050083/\nSeverance"}
                aria-label="Titles to add"
                rows={5}
              />
            </label>
            <div>
              <select value={mediaType} onChange={(event) => setMediaType(event.target.value as typeof mediaType)} aria-label="Bulk title type">
                <option value="either">Movie or TV</option>
                <option value="movie">Movies</option>
                <option value="tv">TV shows</option>
              </select>
              <button className="primary-button" type="button" onClick={previewBulk} disabled={!bulkInput.trim() || searching}>
                {searching ? "Matching…" : "Review matches"}
              </button>
            </div>
          </div>
        )}

        <fieldset className="add-title-destination">
          <legend>Save to</legend>
          <div>
            <button type="button" className={destination === "library" ? "is-active" : ""} aria-pressed={destination === "library"} onClick={() => setDestination("library")}>
              Library<small>Permanent catalog</small>
            </button>
            <button type="button" className={destination === "watch_later" ? "is-active" : ""} aria-pressed={destination === "watch_later"} onClick={() => setDestination("watch_later")}>
              Watch Later<small>Permanent shortlist</small>
            </button>
          </div>
        </fieldset>

        {error ? <div className="inline-error">{error}</div> : null}

        <div className="add-title-results">
          {mode === "single" ? (
            <>
              {!resolution && !searching && !suggesting ? (
                <div className="add-title-guidance">
                  <strong>Start typing for suggestions</strong>
                  <p>Use a direct IMDb or TMDB link when you want one exact match.</p>
                </div>
              ) : null}
              {suggesting ? <div className="add-title-loading">Looking for matches…</div> : null}
              {resolution ? (
                <div className="add-title-result-heading">
                  <strong>{resolution.exact ? "Exact provider match" : "Choose the correct title"}</strong>
                  <span>{resolution.candidates.length} result{resolution.candidates.length === 1 ? "" : "s"}</span>
                </div>
              ) : null}
              {resolution?.candidates.map((candidate) => {
                const key = candidateKey(candidate);
                const selected = key === selectedKey;
                return (
                  <button className={`add-title-candidate ${selected ? "is-selected" : ""}`} type="button" key={key} aria-pressed={selected} onClick={() => setSelectedKey(key)}>
                    {candidate.poster_url ? <img src={candidate.poster_url} alt="" /> : <span className="candidate-placeholder">{candidate.title.slice(0, 1)}</span>}
                    <span className="add-title-candidate-copy">
                      <span>{candidate.media_type === "tv" ? "TV show" : "Movie"}{candidate.release_date ? ` · ${candidate.release_date.slice(0, 4)}` : ""}</span>
                      <strong>{candidate.title}</strong>
                      {candidate.original_title && candidate.original_title !== candidate.title ? <small>{candidate.original_title}</small> : null}
                      <p>{candidate.overview || "Description will be collected when this title is added."}</p>
                    </span>
                    <span className="add-title-candidate-meta">
                      {candidate.tmdb_vote_average != null ? <strong>{candidate.tmdb_vote_average.toFixed(1)}<small>TMDB</small></strong> : null}
                      {candidate.existing_media_item_id ? <em>Already in Library</em> : null}
                      <i aria-hidden="true" />
                    </span>
                  </button>
                );
              })}
            </>
          ) : (
            <>
              {!bulkRows.length ? (
                <div className="add-title-guidance">
                  <strong>Up to {MAX_BULK_TITLES} titles</strong>
                  <p>Duplicates are reused. Review every match before anything is saved.</p>
                </div>
              ) : (
                <div className="bulk-match-list" aria-label="Bulk title matches">
                  <div className="add-title-result-heading"><strong>Review matches</strong><span>{selectedBulkRows.length} ready</span></div>
                  {bulkRows.map((row, index) => (
                    <div className={`bulk-match-row ${row.error ? "has-error" : ""}`} key={`${row.input}:${index}`}>
                      <span>{index + 1}</span>
                      <div><strong>{row.input}</strong>{row.error ? <small>{row.error}</small> : null}</div>
                      {row.resolution ? (
                        <select
                          aria-label={`Match for ${row.input}`}
                          value={row.selectedKey ?? ""}
                          onChange={(event) => setBulkRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, selectedKey: event.target.value || null } : item))}
                        >
                          <option value="">Skip this title</option>
                          {row.resolution.candidates.map((candidate) => (
                            <option key={candidateKey(candidate)} value={candidateKey(candidate)}>
                              {candidate.title} · {candidate.release_date?.slice(0, 4) || "year unknown"} · {candidate.media_type === "tv" ? "TV" : "Movie"}{candidate.existing_media_item_id ? " · already in library" : ""}
                            </option>
                          ))}
                        </select>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <footer className="add-title-footer">
          <p>Metadata and ratings come from TMDB and OMDb. Manual corrections remain protected during future refreshes.</p>
          <button className="primary-button" type="button" onClick={mode === "bulk" ? addBulk : addSelected} disabled={mode === "bulk" ? !selectedBulkRows.length || committing : !selectedCandidate || committing}>
            {committing
              ? mode === "bulk" ? `Adding ${commitProgress}…` : "Collecting metadata…"
              : destination === "watch_later"
                ? mode === "bulk" ? `Add ${selectedBulkRows.length} to Watch Later` : "Add to Watch Later"
                : mode === "bulk" ? `Add ${selectedBulkRows.length} to Library` : "Add to Library"}
          </button>
        </footer>
      </section>
    </div>
  );
}
