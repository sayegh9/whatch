import { useEffect, useState } from "react";
import {
  commitImport,
  fetchMetadataReadiness,
  previewImport,
  retryMetadataJobs,
  startMetadataBackfill,
} from "../api";
import { ImportSummary } from "../components/ImportSummary";
import type { ImportStats, MetadataReadiness } from "../types";

interface Props {
  current: ImportStats | null;
  onChange: (stats: ImportStats) => void;
  onComplete: () => void;
}

export function ImportScreen({ current, onChange, onComplete }: Props) {
  const [stats, setStats] = useState<ImportStats | null>(current);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<MetadataReadiness | null>(null);
  const [metadataWorking, setMetadataWorking] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    async function loadReadiness() {
      try {
        const result = await fetchMetadataReadiness();
        if (!active) return;
        setReadiness(result);
        if (result.queued || result.running) {
          timer = window.setTimeout(loadReadiness, 2000);
        }
      } catch {
        // Catalog import remains usable when provider readiness is unavailable.
      }
    }
    void loadReadiness();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  async function runMetadataMaintenance(retry = false) {
    setMetadataWorking(true);
    setError(null);
    try {
      const result = retry ? await retryMetadataJobs(10) : await startMetadataBackfill(10);
      setReadiness(result.readiness);
      window.setTimeout(async function pollReadiness() {
        try {
          const latest = await fetchMetadataReadiness();
          setReadiness(latest);
          if (latest.queued || latest.running) window.setTimeout(pollReadiness, 2000);
        } catch {
          // A later visit will fetch the durable job state again.
        }
      }, 2000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Metadata refresh could not start");
    } finally {
      setMetadataWorking(false);
    }
  }

  async function preview() {
    setWorking(true);
    try {
      const result = await previewImport();
      setStats(result);
      onChange(result);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import preview failed");
    } finally {
      setWorking(false);
    }
  }

  async function commit() {
    if (!stats) return;
    setWorking(true);
    try {
      const result = await commitImport(stats.job_id);
      setStats(result);
      onChange(result);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import failed");
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="focused-screen">
      <header className="screen-header">
        <h1>Import catalog</h1>
        <p>
          The Markdown file remains unchanged. Exact IMDb duplicates are merged while every
          distinct source link is preserved.
        </p>
      </header>
      <section className="import-panel">
        <div className="source-file">
          <span>Source file</span>
          <strong>bookmark_movies_tv_series_with_ratings.md</strong>
        </div>
        {stats ? <ImportSummary stats={stats} /> : (
          <div className="import-explainer">
            <h2>Preview before committing</h2>
            <p>No catalog records will be created until you approve the preview.</p>
          </div>
        )}
        {error ? <div className="inline-error">{error}</div> : null}
        <div className="import-actions">
          {!stats || stats.status === "committed" ? (
            <button className="secondary-button" onClick={preview} disabled={working}>
              {working ? "Reading…" : stats ? "Preview again" : "Create preview"}
            </button>
          ) : null}
          {stats?.status === "preview" ? (
            <button className="primary-button" onClick={commit} disabled={working}>
              {working ? "Importing…" : "Commit import"}
            </button>
          ) : null}
          {stats?.status === "committed" ? (
            <button className="primary-button" onClick={onComplete}>View library</button>
          ) : null}
        </div>
        {stats?.status === "committed" ? (
          <p className="success-message">
            Import committed. {stats.canonical_candidates} canonical catalog entries were
            identified and {stats.review_rows} rows remain available for review.
          </p>
        ) : null}
      </section>
      <section className="metadata-maintenance" aria-labelledby="metadata-maintenance-heading">
        <div className="section-heading">
          <div>
            <span>Background jobs</span>
            <h2 id="metadata-maintenance-heading">Metadata maintenance</h2>
          </div>
          {readiness ? <strong>{readiness.enriched} / {readiness.eligible} enriched</strong> : null}
        </div>
        <p>Fill missing posters, runtimes, genres, descriptions, and ratings without blocking the app. Manual corrections stay protected.</p>
        {readiness ? (
          <div className="metadata-readiness-grid">
            <div><span>Queued</span><strong>{readiness.queued}</strong></div>
            <div><span>Running</span><strong>{readiness.running}</strong></div>
            <div><span>Failed</span><strong>{readiness.failed}</strong></div>
            <div><span>Need enrichment</span><strong>{Math.max(0, readiness.eligible - readiness.enriched)}</strong></div>
          </div>
        ) : <div className="add-title-loading">Loading catalog readiness…</div>}
        <div className="import-actions">
          {readiness?.failed ? <button className="secondary-button" type="button" disabled={metadataWorking} onClick={() => runMetadataMaintenance(true)}>Retry failed</button> : null}
          <button className="primary-button" type="button" disabled={metadataWorking || !readiness || readiness.enriched >= readiness.eligible} onClick={() => runMetadataMaintenance(false)}>
            {metadataWorking ? "Starting…" : "Enrich next 10 in background"}
          </button>
        </div>
      </section>
    </main>
  );
}
