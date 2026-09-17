import type { ImportStats } from "../types";

interface Props {
  stats: ImportStats;
  compact?: boolean;
}

export function ImportSummary({ stats, compact = false }: Props) {
  if (compact) {
    return (
      <div className="import-summary-compact">
        <span>{stats.total_rows} rows</span>
        <i />
        <span>{stats.duplicate_rows} duplicates</span>
        <i />
        <strong>{stats.review_rows} to review</strong>
      </div>
    );
  }
  return (
    <dl className="import-metrics">
      <div>
        <dt>Raw rows</dt>
        <dd>{stats.total_rows}</dd>
      </div>
      <div>
        <dt>Matched rows</dt>
        <dd>{stats.matched_rows}</dd>
      </div>
      <div>
        <dt>Duplicate rows</dt>
        <dd>{stats.duplicate_rows}</dd>
      </div>
      <div>
        <dt>Needs review</dt>
        <dd>{stats.review_rows}</dd>
      </div>
      <div>
        <dt>Catalog candidates</dt>
        <dd>{stats.canonical_candidates}</dd>
      </div>
    </dl>
  );
}

