import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  addTitleToWatchLater,
  fetchTitle,
  fetchTitles,
  refreshTitleMetadata,
  removeTitleFromWatchLater,
  updateTitle,
} from "../api";
import { DetailDrawer } from "../components/DetailDrawer";
import { ImportSummary } from "../components/ImportSummary";
import {
  MediaTable,
  type SortDirection,
  type SortKey,
} from "../components/MediaTable";
import { SearchIcon } from "../icons";
import type {
  ImportStats,
  RecommendationSeed,
  TitleDetail,
  TitleListResponse,
  TitleSummary,
} from "../types";

interface Props {
  importStats: ImportStats | null;
  onImport: () => void;
  onFindSimilar: (seeds: RecommendationSeed[]) => void;
  onWatchLaterChange: () => Promise<void>;
}

const EMPTY_LIST: TitleListResponse = { items: [], total: 0, page: 1, page_size: 50 };
const MAX_SIMILARITY_SEEDS = 20;
const DEFAULT_SORT_DIRECTION: Record<SortKey, SortDirection> = {
  title: "asc",
  type: "asc",
  genre: "asc",
  year: "desc",
  imdb: "desc",
  rt: "desc",
  status: "asc",
  priority: "desc",
  sources: "desc",
};

export function LibraryScreen({
  importStats,
  onImport,
  onFindSimilar,
  onWatchLaterChange,
}: Props) {
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [mediaType, setMediaType] = useState("all");
  const [status, setStatus] = useState("all");
  const [yearMin, setYearMin] = useState("all");
  const [ratingMin, setRatingMin] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("title");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<TitleListResponse>(EMPTY_LIST);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [bulkSelection, setBulkSelection] = useState<Map<number, RecommendationSeed>>(
    () => new Map(),
  );
  const [detail, setDetail] = useState<TitleDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bulkWatchLaterBusy, setBulkWatchLaterBusy] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "50",
      sort: `${sortKey}_${sortDirection}`,
    });
    if (deferredSearch) params.set("q", deferredSearch);
    if (mediaType !== "all") params.set("media_type", mediaType);
    if (status !== "all") params.set("status", status);
    if (yearMin !== "all") params.set("year_min", yearMin);
    if (ratingMin !== "all") params.set("imdb_min", ratingMin);
    return params;
  }, [
    deferredSearch,
    mediaType,
    page,
    ratingMin,
    sortDirection,
    sortKey,
    status,
    yearMin,
  ]);

  useEffect(() => {
    let active = true;
    setLoadingList(true);
    fetchTitles(query)
      .then((payload) => {
        if (active) {
          setList(payload);
          setError(null);
        }
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoadingList(false));
    return () => {
      active = false;
    };
  }, [query]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    setLoadingDetail(true);
    fetchTitle(selectedId)
      .then((payload) => active && setDetail(payload))
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoadingDetail(false));
    return () => {
      active = false;
    };
  }, [selectedId]);

  async function saveDetail(payload: Record<string, unknown>) {
    if (!selectedId) return;
    const updated = await updateTitle(selectedId, payload);
    setDetail(updated);
    setList((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === updated.id ? { ...item, ...updated } : item,
      ),
    }));
  }

  async function refreshDetail() {
    if (!selectedId) return;
    await refreshTitleMetadata(selectedId);
    const updated = await fetchTitle(selectedId);
    setDetail(updated);
    setList((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === updated.id ? { ...item, ...updated } : item,
      ),
    }));
  }

  async function toggleDetailWatchLater() {
    if (!detail) return;
    try {
      let updated: TitleDetail;
      if (detail.watch_later) {
        await removeTitleFromWatchLater(detail.id);
        updated = { ...detail, watch_later: false };
      } else {
        updated = await addTitleToWatchLater(detail.id);
      }
      setDetail(updated);
      setList((current) => ({
        ...current,
        items: current.items.map((item) =>
          item.id === updated.id ? { ...item, watch_later: updated.watch_later } : item,
        ),
      }));
      await onWatchLaterChange();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update Watch Later");
    }
  }

  async function addBulkToWatchLater() {
    setBulkWatchLaterBusy(true);
    setError(null);
    const ids = [...bulkSelection.keys()];
    try {
      await Promise.all(ids.map((id) => addTitleToWatchLater(id)));
      const selectedIds = new Set(ids);
      setList((current) => ({
        ...current,
        items: current.items.map((item) =>
          selectedIds.has(item.id) ? { ...item, watch_later: true } : item,
        ),
      }));
      if (detail && selectedIds.has(detail.id)) {
        setDetail({ ...detail, watch_later: true });
      }
      await onWatchLaterChange();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update Watch Later");
    } finally {
      setBulkWatchLaterBusy(false);
    }
  }

  function sortBy(key: SortKey) {
    setPage(1);
    if (key === sortKey) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(key);
    setSortDirection(DEFAULT_SORT_DIRECTION[key]);
  }

  function toggleBulkSelection(item: TitleSummary) {
    setBulkSelection((current) => {
      const next = new Map(current);
      if (next.has(item.id)) {
        next.delete(item.id);
      } else if (next.size < MAX_SIMILARITY_SEEDS) {
        next.set(item.id, {
          id: item.id,
          title: item.title,
          media_type: item.media_type,
          year: item.start_year,
        });
      }
      return next;
    });
  }

  function toggleVisibleSelection(items: TitleSummary[]) {
    setBulkSelection((current) => {
      const next = new Map(current);
      const allVisibleSelected = items.length > 0
        && items.every((item) => next.has(item.id));
      for (const item of items) {
        if (allVisibleSelected) {
          next.delete(item.id);
        } else if (next.size < MAX_SIMILARITY_SEEDS) {
          next.set(item.id, {
            id: item.id,
            title: item.title,
            media_type: item.media_type,
            year: item.start_year,
          });
        }
      }
      return next;
    });
  }

  const pageCount = Math.max(1, Math.ceil(list.total / list.page_size));
  const bulkSelectedIds = useMemo(
    () => new Set(bulkSelection.keys()),
    [bulkSelection],
  );

  return (
    <main className={`library-layout ${selectedId ? "has-drawer" : ""}`}>
      <section className="catalog-pane">
        <div className="page-heading">
          <div>
            <h1>Your library</h1>
            <p>{list.total} titles in this view</p>
          </div>
          {importStats ? <ImportSummary stats={importStats} compact /> : null}
        </div>
        <div className="filter-bar">
          <label className="search-field">
            <SearchIcon />
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Search titles, notes, tags…"
              aria-label="Search catalog"
            />
          </label>
          <select
            value={mediaType}
            onChange={(event) => {
              setMediaType(event.target.value);
              setPage(1);
            }}
            aria-label="Media type"
          >
            <option value="all">All media</option>
            <option value="movie">Movies</option>
            <option value="tv">TV shows</option>
          </select>
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
            aria-label="Watch status"
          >
            <option value="all">All statuses</option>
            <option value="want_to_watch">Want to watch</option>
            <option value="watching">Watching</option>
            <option value="watched">Watched</option>
            <option value="dropped">Dropped</option>
            <option value="maybe_later">Maybe later</option>
            <option value="hidden">Hidden</option>
          </select>
          <select
            value={yearMin}
            onChange={(event) => {
              setYearMin(event.target.value);
              setPage(1);
            }}
            aria-label="Release years"
          >
            <option value="all">All years</option>
            <option value="2020">2020 and newer</option>
            <option value="2010">2010 and newer</option>
            <option value="2000">2000 and newer</option>
            <option value="1980">1980 and newer</option>
          </select>
          <select
            value={ratingMin}
            onChange={(event) => {
              setRatingMin(event.target.value);
              setPage(1);
            }}
            aria-label="IMDb rating"
          >
            <option value="all">All ratings</option>
            <option value="8">IMDb 8+</option>
            <option value="7">IMDb 7+</option>
            <option value="6">IMDb 6+</option>
          </select>
        </div>
        {error ? <div className="inline-error">{error}</div> : null}
        {bulkSelection.size ? (
          <div className="bulk-recommendation-bar" role="status">
            <div>
              <strong>{bulkSelection.size} selected</strong>
              <span>
                Use these titles as explicit similarity seeds · up to{" "}
                {MAX_SIMILARITY_SEEDS}
              </span>
            </div>
            <div>
              <button
                className="text-button"
                type="button"
                onClick={addBulkToWatchLater}
                disabled={bulkWatchLaterBusy}
              >
                {bulkWatchLaterBusy ? "Adding…" : "Add to Watch Later"}
              </button>
              <button
                className="text-button"
                type="button"
                onClick={() => setBulkSelection(new Map())}
              >
                Clear
              </button>
              <button
                className="primary-button"
                type="button"
                onClick={() => onFindSimilar([...bulkSelection.values()])}
              >
                Find similar
              </button>
            </div>
          </div>
        ) : null}
        {!importStats && !loadingList ? (
          <div className="first-import">
            <h2>Bring in your current list</h2>
            <p>
              Preview the Markdown catalog, merge exact IMDb duplicates, and keep ambiguous
              entries for review.
            </p>
            <button className="primary-button" onClick={onImport}>Open import</button>
          </div>
        ) : (
          <MediaTable
            items={list.items}
            selectedId={selectedId}
            selectedIds={bulkSelectedIds}
            loading={loadingList}
            sortKey={sortKey}
            sortDirection={sortDirection}
            onSelect={setSelectedId}
            onToggleSelection={toggleBulkSelection}
            onToggleVisible={toggleVisibleSelection}
            onSort={sortBy}
          />
        )}
        <footer className="table-footer">
          <span>{list.total} titles</span>
          <div className="pagination">
            <button
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous
            </button>
            <span>{page} / {pageCount}</span>
            <button
              disabled={page >= pageCount}
              onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
            >
              Next
            </button>
          </div>
        </footer>
      </section>
      <DetailDrawer
        detail={detail}
        loading={loadingDetail}
        onClose={() => setSelectedId(null)}
        onSave={saveDetail}
        onRefresh={refreshDetail}
        onToggleWatchLater={toggleDetailWatchLater}
      />
    </main>
  );
}
