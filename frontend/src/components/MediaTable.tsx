import { useState } from "react";

import type { TitleSummary } from "../types";

export type SortKey =
  | "title"
  | "type"
  | "genre"
  | "year"
  | "imdb"
  | "rt"
  | "status"
  | "priority"
  | "sources";

export type SortDirection = "asc" | "desc";

interface Props {
  items: TitleSummary[];
  selectedId: number | null;
  selectedIds: Set<number>;
  loading: boolean;
  sortKey: SortKey;
  sortDirection: SortDirection;
  onSelect: (id: number) => void;
  onToggleSelection: (item: TitleSummary) => void;
  onToggleVisible: (items: TitleSummary[]) => void;
  onSort: (key: SortKey) => void;
}

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: "title", label: "Title" },
  { key: "type", label: "Type" },
  { key: "genre", label: "Genre" },
  { key: "year", label: "Year" },
  { key: "imdb", label: "IMDb" },
  { key: "rt", label: "RT" },
  { key: "status", label: "Status" },
  { key: "priority", label: "Priority" },
  { key: "sources", label: "Sources" },
];

function displayYear(item: TitleSummary) {
  if (!item.start_year) return "—";
  if (item.is_ongoing) return `${item.start_year}–`;
  if (item.end_year) return `${item.start_year}–${item.end_year}`;
  return String(item.start_year);
}

function monogram(title: string) {
  return title.replace(/^(the|a|an)\s+/i, "").slice(0, 1).toUpperCase();
}

function priorityLabel(priority: string) {
  if (priority === "high") return "High";
  if (priority === "low") return "Low";
  return "Normal";
}

function TitleThumbnail({ item }: { item: TitleSummary }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showPoster = Boolean(item.poster_url && failedUrl !== item.poster_url);

  if (showPoster) {
    return (
      <img
        className="cover-thumbnail"
        src={item.poster_url ?? undefined}
        alt=""
        loading="lazy"
        onError={() => setFailedUrl(item.poster_url)}
      />
    );
  }

  return (
    <span className={`cover-monogram cover-${item.id % 6}`}>
      {monogram(item.title)}
    </span>
  );
}

export function MediaTable({
  items,
  selectedId,
  selectedIds,
  loading,
  sortKey,
  sortDirection,
  onSelect,
  onToggleSelection,
  onToggleVisible,
  onSort,
}: Props) {
  return (
    <div className={`media-table-wrap ${loading ? "is-loading" : ""}`}>
      <table className="media-table">
        <thead>
          <tr>
            <th className="selection-column">
              <input
                type="checkbox"
                aria-label="Select all visible titles"
                checked={items.length > 0 && items.every((item) => selectedIds.has(item.id))}
                onChange={() => onToggleVisible(items)}
              />
            </th>
            {COLUMNS.map((column) => {
              const active = sortKey === column.key;
              return (
                <th
                  key={column.key}
                  className={`column-${column.key}`}
                  aria-sort={
                    active
                      ? sortDirection === "asc" ? "ascending" : "descending"
                      : "none"
                  }
                >
                  <button
                    className={`table-sort-button ${active ? "is-active" : ""}`}
                    type="button"
                    onClick={() => onSort(column.key)}
                    title={`Sort by ${column.label}`}
                  >
                    <span>{column.label}</span>
                    <i aria-hidden="true">
                      {active ? sortDirection === "asc" ? "↑" : "↓" : "↕"}
                    </i>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className={[
                selectedId === item.id ? "is-selected" : "",
                selectedIds.has(item.id) ? "is-bulk-selected" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => onSelect(item.id)}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelect(item.id);
              }}
            >
              <td className="selection-column">
                <input
                  type="checkbox"
                  aria-label={`Select ${item.title} for similar recommendations`}
                  checked={selectedIds.has(item.id)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => onToggleSelection(item)}
                />
              </td>
              <td className="column-title">
                <div className="title-cell">
                  <TitleThumbnail item={item} />
                  <div>
                    <strong>{item.title}</strong>
                    <span className="mobile-row-meta">
                      {item.media_type === "tv" ? "TV show" : "Movie"}
                      {" · "}
                      {displayYear(item)}
                      {" · "}
                      {(item.genres ?? []).slice(0, 1).join("") || "Genre unknown"}
                    </span>
                    {item.tags.length ? (
                      <span className="row-tags">{item.tags.slice(0, 2).join(" · ")}</span>
                    ) : null}
                  </div>
                </div>
              </td>
              <td className="column-type">{item.media_type === "tv" ? "TV show" : "Movie"}</td>
              <td className="column-genre" title={(item.genres ?? []).join(", ")}>
                {(item.genres ?? []).slice(0, 2).join(" · ") || "—"}
              </td>
              <td className="column-year">{displayYear(item)}</td>
              <td className="column-imdb">{item.imdb_rating?.toFixed(1) ?? "—"}</td>
              <td className="column-rt rt-value">
                {item.rotten_tomatoes_rating != null
                  ? `${Math.round(item.rotten_tomatoes_rating)}%`
                  : "—"}
              </td>
              <td className="column-status">
                <span className={`status-text status-${item.status}`}>
                  {item.status.replaceAll("_", " ")}
                </span>
              </td>
              <td className="column-priority">
                <span className={`priority priority-${item.priority}`}>
                  {priorityLabel(item.priority)}
                </span>
              </td>
              <td className="column-sources">{item.link_count} {item.link_count === 1 ? "link" : "links"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && items.length === 0 ? (
        <div className="empty-table">
          <strong>No titles found</strong>
          <span>Change the filters or import the current catalog.</span>
        </div>
      ) : null}
    </div>
  );
}
