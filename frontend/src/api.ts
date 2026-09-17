import type {
  AgentRecommendationResponse,
  ImportStats,
  MetadataCandidate,
  MetadataBackfillResponse,
  MetadataJob,
  MetadataReadiness,
  RecommendationAgentStatus,
  InternetRecommendationResponse,
  IntakeCommitResponse,
  IntakeResolveResponse,
  LocalRecommendationResponse,
  ReviewRow,
  TitleDetail,
  TitleListResponse,
  WatchLaterResponse,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ?? `Request failed (${response.status})`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function fetchTitles(params: URLSearchParams) {
  return request<TitleListResponse>(`/api/titles?${params.toString()}`);
}

export function fetchTitle(id: number) {
  return request<TitleDetail>(`/api/titles/${id}`);
}

export function resolveTitleIntake(payload: {
  input: string;
  media_type: "either" | "movie" | "tv";
}) {
  return request<IntakeResolveResponse>("/api/intake/resolve", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function commitTitleIntake(payload: {
  tmdb_id: number;
  media_type: "movie" | "tv";
  destination: "library" | "watch_later";
  source_url?: string;
}) {
  return request<IntakeCommitResponse>("/api/intake/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchWatchLater() {
  return request<WatchLaterResponse>("/api/watch-later");
}

export function addTitleToWatchLater(id: number) {
  return request<TitleDetail>(`/api/watch-later/title/${id}`, {
    method: "POST",
  });
}

export function removeTitleFromWatchLater(id: number) {
  return request<void>(`/api/watch-later/title/${id}`, {
    method: "DELETE",
  });
}

export function moveWatchLaterToLibrary(id: number, watched: boolean) {
  return request<TitleDetail>(`/api/watch-later/title/${id}/move-to-library`, {
    method: "POST",
    body: JSON.stringify({ watched }),
  });
}

export function addDiscoveryToWatchLater(candidateId: number) {
  return request<TitleDetail>(`/api/watch-later/discovery/${candidateId}`, {
    method: "POST",
  });
}

export function updateTitle(id: number, payload: Record<string, unknown>) {
  return request<TitleDetail>(`/api/titles/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function refreshTitleMetadata(id: number) {
  return request<MetadataJob>(`/api/titles/${id}/metadata/refresh`, {
    method: "POST",
  });
}

export function fetchMetadataReadiness() {
  return request<MetadataReadiness>("/api/metadata/readiness");
}

export function startMetadataBackfill(limit = 5) {
  return request<MetadataBackfillResponse>("/api/metadata/backfill", {
    method: "POST",
    body: JSON.stringify({ limit }),
  });
}

export function retryMetadataJobs(limit = 5) {
  return request<MetadataBackfillResponse>("/api/metadata/jobs/retry", {
    method: "POST",
    body: JSON.stringify({ limit }),
  });
}

export function latestImport() {
  return request<ImportStats | null>("/api/import/latest");
}

export function previewImport() {
  return request<ImportStats>("/api/import/markdown", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function commitImport(jobId: number) {
  return request<ImportStats>(`/api/import/commit/${jobId}`, { method: "POST" });
}

export function fetchReview() {
  return request<ReviewRow[]>("/api/review");
}

export function resolveReview(
  id: number,
  payload: {
    action: "ignore" | "create" | "merge";
    title?: string;
    media_type?: string;
    start_year?: number;
    media_item_id?: number;
  },
) {
  return request<ReviewRow>(`/api/review/${id}/resolve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function searchMetadata(payload: {
  title: string;
  media_type: "movie" | "tv";
  year?: number;
}) {
  return request<MetadataCandidate[]>("/api/metadata/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resolveReviewMetadata(
  id: number,
  candidate: Pick<MetadataCandidate, "tmdb_id" | "media_type">,
) {
  return request<ReviewRow>(`/api/review/${id}/resolve-metadata`, {
    method: "POST",
    body: JSON.stringify(candidate),
  });
}

export function recommendLocal(payload: {
  prompt?: string;
  media_type: "either" | "movie" | "tv";
  runtime_max?: number;
  imdb_min?: number;
  rt_min?: number;
  genres: string[];
  excluded_genres: string[];
  genre_mode: "prefer" | "require";
  release_year_mode: "any" | "before" | "after";
  release_year?: number;
  language?: string;
  production_country?: string;
  seed_title_ids: number[];
  adventure: "safe" | "adjacent" | "adventurous";
  tone: "any" | "light" | "balanced" | "dark";
  pace: "any" | "relaxed" | "balanced" | "fast";
  company: "any" | "solo" | "group";
  strict_metadata: boolean;
  limit: number;
}) {
  return request<LocalRecommendationResponse>("/api/recommend/local", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function dismissRecommendation(id: number, reason = "not_interested") {
  return request<void>(`/api/recommend/dismiss/${id}`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function recommendInternet(payload: {
  prompt?: string;
  media_type: "either" | "movie" | "tv";
  runtime_max?: number;
  imdb_min?: number;
  rt_min?: number;
  genres: string[];
  excluded_genres: string[];
  genre_mode: "prefer" | "require";
  release_year_mode: "any" | "before" | "after";
  release_year?: number;
  language?: string;
  production_country?: string;
  seed_title_ids: number[];
  adventure: "safe" | "adjacent" | "adventurous";
  tone: "any" | "light" | "balanced" | "dark";
  pace: "any" | "relaxed" | "balanced" | "fast";
  company: "any" | "solo" | "group";
  strict_metadata: boolean;
  limit: number;
}) {
  return request<InternetRecommendationResponse>("/api/recommend/internet", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchRecommendationAgentStatus() {
  return request<RecommendationAgentStatus>("/api/recommend/agent/status");
}

export function recommendAgent(payload: {
  prompt?: string;
  media_type: "either" | "movie" | "tv";
  runtime_max?: number;
  imdb_min?: number;
  rt_min?: number;
  genres: string[];
  excluded_genres: string[];
  genre_mode: "prefer" | "require";
  release_year_mode: "any" | "before" | "after";
  release_year?: number;
  language?: string;
  production_country?: string;
  seed_title_ids: number[];
  adventure: "safe" | "adjacent" | "adventurous";
  tone: "any" | "light" | "balanced" | "dark";
  pace: "any" | "relaxed" | "balanced" | "fast";
  company: "any" | "solo" | "group";
  strict_metadata: boolean;
  limit: number;
  scope: "local" | "internet" | "hybrid";
  cloud_consent: boolean;
}) {
  return request<AgentRecommendationResponse>("/api/recommend/agent", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function recordRecommendationFeedback(payload: {
  session_id: number;
  source: "local" | "internet";
  action:
    | "impression"
    | "opened_details"
    | "opened_watch_link"
    | "selected"
    | "added"
    | "watched"
    | "liked"
    | "disliked"
    | "skipped"
    | "not_tonight"
    | "not_interested"
    | "already_watched"
    | "too_long"
    | "wrong_mood"
    | "seen_similar_recently"
    | "more_like_this"
    | "less_like_this"
    | "dismissed";
  media_item_id?: number;
  candidate_id?: number;
}) {
  return request<{ id: number; recorded: boolean }>("/api/recommend/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function dismissInternetRecommendation(
  mediaType: "movie" | "tv",
  tmdbId: number,
  reason = "not_interested",
) {
  return request<void>(`/api/recommend/internet/dismiss/${mediaType}/${tmdbId}`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function addInternetRecommendation(candidateId: number) {
  return request<{ media_item_id: number; created: boolean }>(
    `/api/recommend/internet/add/${candidateId}`,
    { method: "POST" },
  );
}
