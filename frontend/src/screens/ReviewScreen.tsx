import { useEffect, useState } from "react";
import {
  fetchReview,
  resolveReview,
  resolveReviewMetadata,
  searchMetadata,
} from "../api";
import { ExternalIcon } from "../icons";
import type { MetadataCandidate, ReviewRow } from "../types";

interface Props {
  onCountChange: (count: number) => void;
}

export function ReviewScreen({ onCountChange }: Props) {
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [candidateRowId, setCandidateRowId] = useState<number | null>(null);
  const [candidates, setCandidates] = useState<MetadataCandidate[]>([]);
  const [searching, setSearching] = useState(false);

  function refresh() {
    setLoading(true);
    fetchReview()
      .then((result) => {
        setRows(result);
        onCountChange(result.length);
        setError(null);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function resolve(row: ReviewRow, action: "ignore" | "create") {
    try {
      await resolveReview(row.id, {
        action,
        title: row.raw_title,
        media_type: row.raw_section,
        start_year: row.raw_year?.match(/^\d{4}/) ? Number(row.raw_year.slice(0, 4)) : undefined,
      });
      setRows((current) => current.filter((item) => item.id !== row.id));
      onCountChange(rows.length - 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not resolve row");
    }
  }

  async function findMatches(row: ReviewRow) {
    setCandidateRowId(row.id);
    setCandidates([]);
    setSearching(true);
    setError(null);
    try {
      const year = row.raw_year?.match(/^\d{4}/) ? Number(row.raw_year.slice(0, 4)) : undefined;
      setCandidates(
        await searchMetadata({
          title: row.raw_title,
          media_type: row.raw_section,
          year,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not search metadata");
    } finally {
      setSearching(false);
    }
  }

  async function chooseMatch(row: ReviewRow, candidate: MetadataCandidate) {
    try {
      await resolveReviewMetadata(row.id, candidate);
      setRows((current) => current.filter((item) => item.id !== row.id));
      onCountChange(rows.length - 1);
      setCandidateRowId(null);
      setCandidates([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not resolve match");
    }
  }

  return (
    <main className="focused-screen review-screen">
      <header className="screen-header">
        <h1>Needs review</h1>
        <p>
          These rows did not contain a reliable external identity. Create genuine titles or
          ignore index and directory pages.
        </p>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      <div className="review-list">
        {loading ? <p className="loading-copy">Loading review queue…</p> : null}
        {!loading && rows.length === 0 ? (
          <div className="review-empty">
            <h2>Review queue cleared</h2>
            <p>Every ambiguous import row has been resolved.</p>
          </div>
        ) : null}
        {rows.map((row) => (
          <article className="review-row" key={row.id}>
            <div className="review-main">
              <span>{row.raw_section === "tv" ? "TV show" : "Movie"} · {row.raw_year ?? "Year unknown"}</span>
              <h2>{row.raw_title}</h2>
              <p>{row.match_status}</p>
            </div>
            {row.raw_url ? (
              <a href={row.raw_url} target="_blank" rel="noopener noreferrer">
                {new URL(row.raw_url).hostname.replace(/^www\./, "")}
                <ExternalIcon />
              </a>
            ) : null}
            <div className="review-actions">
              <button className="text-button" onClick={() => resolve(row, "ignore")}>
                Ignore page
              </button>
              <button className="secondary-button" onClick={() => resolve(row, "create")}>
                Create title
              </button>
              <button className="primary-button" onClick={() => findMatches(row)}>
                Find matches
              </button>
            </div>
            {candidateRowId === row.id ? (
              <div className="candidate-panel">
                {searching ? <p>Searching TMDB…</p> : null}
                {!searching && candidates.length === 0 ? <p>No candidates found.</p> : null}
                {candidates.map((candidate) => (
                  <button
                    className="candidate-card"
                    key={`${candidate.media_type}-${candidate.tmdb_id}`}
                    onClick={() => chooseMatch(row, candidate)}
                  >
                    {candidate.poster_url ? (
                      <img src={candidate.poster_url} alt="" />
                    ) : (
                      <span className="candidate-placeholder" />
                    )}
                    <span>
                      <strong>{candidate.title}</strong>
                      <small>{candidate.release_date?.slice(0, 4) ?? "Year unknown"}</small>
                      <em>{candidate.overview || "No overview available."}</em>
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </main>
  );
}
