export type Screen = "library" | "watch_later" | "tonight" | "review" | "import";

export interface RecommendationSeed {
  id: number;
  title: string;
  media_type: "movie" | "tv";
  year: number | null;
}

export interface ImportStats {
  job_id: number;
  total_rows: number;
  matched_rows: number;
  duplicate_rows: number;
  review_rows: number;
  canonical_candidates: number;
  status: "preview" | "committed";
}

export interface MediaLink {
  id: number;
  url: string;
  domain: string;
  link_type: string;
  archived: boolean;
}

export interface TitleSummary {
  id: number;
  title: string;
  media_type: "movie" | "tv";
  start_year: number | null;
  end_year: number | null;
  is_ongoing: boolean;
  imdb_id: string | null;
  imdb_rating: number | null;
  rotten_tomatoes_rating: number | null;
  poster_url: string | null;
  metadata_status: string;
  status: string;
  priority: string;
  user_rating: number | null;
  link_count: number;
  tags: string[];
  genres: string[];
  watch_later: boolean;
}

export interface TitleDetail extends TitleSummary {
  original_title: string | null;
  runtime_minutes: number | null;
  release_date: string | null;
  genres: string[];
  original_language: string | null;
  overview: string | null;
  metacritic_rating: number | null;
  tmdb_vote_average: number | null;
  tmdb_vote_count: number | null;
  metadata_refreshed_at: string | null;
  manual_fields: string[];
  notes: string | null;
  links: MediaLink[];
}

export interface TitleListResponse {
  items: TitleSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface WatchLaterItem extends TitleSummary {
  added_at: string;
}

export interface WatchLaterResponse {
  items: WatchLaterItem[];
  total: number;
}

export interface ReviewRow {
  id: number;
  raw_title: string;
  raw_year: string | null;
  raw_section: "movie" | "tv";
  raw_url: string | null;
  match_status: string;
  proposed_action: string;
  confidence: number;
  resolution_status: string;
}

export interface MetadataJob {
  id: number;
  media_item_id: number | null;
  job_type: string;
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  error_code: string | null;
  error_message: string | null;
}

export interface MetadataReadiness {
  total: number;
  eligible: number;
  enriched: number;
  runtime: number;
  genres: number;
  overview: number;
  queued: number;
  running: number;
  failed: number;
}

export interface MetadataBackfillResponse {
  queued_job_ids: number[];
  readiness: MetadataReadiness;
}

export interface MetadataCandidate {
  tmdb_id: number;
  media_type: "movie" | "tv";
  title: string;
  original_title: string | null;
  release_date: string | null;
  overview: string | null;
  poster_url: string | null;
}

export interface IntakeCandidate {
  tmdb_id: number;
  media_type: "movie" | "tv";
  title: string;
  original_title: string | null;
  release_date: string | null;
  overview: string | null;
  poster_url: string | null;
  tmdb_vote_average: number | null;
  existing_media_item_id: number | null;
}

export interface IntakeResolveResponse {
  input_kind: "title" | "imdb_url" | "tmdb_url" | "rt_url";
  exact: boolean;
  normalized_input: string;
  source_url: string | null;
  candidates: IntakeCandidate[];
}

export interface IntakeCommitResponse {
  item: TitleDetail;
  created: boolean;
  destination: "library" | "watch_later";
}

export interface RecommendationResult {
  title_id: number;
  title: string;
  media_type: "movie" | "tv";
  year: number | null;
  runtime_minutes: number | null;
  genres: string[];
  original_language: string | null;
  production_countries: string[];
  poster_url: string | null;
  imdb_id: string | null;
  imdb_rating: number | null;
  rotten_tomatoes_rating: number | null;
  status: string;
  priority: string;
  watch_later: boolean;
  score: number;
  score_breakdown: Record<string, number>;
  reasons: string[];
  agent_reason: string | null;
  agent_tradeoff: string | null;
  links: Array<{ url: string; domain: string }>;
}

export interface LocalRecommendationResponse {
  session_id: number;
  mode: "local";
  confidence: "low" | "medium" | "high";
  confidence_reason: string;
  candidate_count: number;
  metadata_coverage: {
    total: number;
    runtime: number;
    genres: number;
    overview: number;
  };
  criteria: Record<string, unknown>;
  results: RecommendationResult[];
}

export interface DiscoveryResult {
  candidate_id: number;
  tmdb_id: number;
  media_type: "movie" | "tv";
  imdb_id: string | null;
  title: string;
  year: number | null;
  runtime_minutes: number | null;
  genres: string[];
  original_language: string | null;
  production_countries: string[];
  overview: string | null;
  poster_url: string | null;
  imdb_rating: number | null;
  rotten_tomatoes_rating: number | null;
  tmdb_vote_average: number | null;
  score: number;
  score_breakdown: Record<string, number>;
  reasons: string[];
  agent_reason: string | null;
  agent_tradeoff: string | null;
  seed_titles: string[];
  tmdb_url: string;
}

export interface InternetRecommendationResponse {
  session_id: number;
  mode: "internet";
  confidence: "low" | "medium" | "high";
  candidate_count: number;
  criteria: Record<string, unknown>;
  results: DiscoveryResult[];
  search_queries: string[];
}

export interface RecommendationAgentStatus {
  available: boolean;
  enabled: boolean;
  configured: boolean;
  model: string;
  privacy_summary: string;
}

export interface AgentRecommendationResponse {
  session_id: number;
  provider: "gemini" | "deterministic";
  model: string | null;
  summary: string;
  interpreted_preferences: string[];
  fallback_reason: string | null;
  search_plan: {
    strategy: string;
    queries: string[];
  } | null;
  local: LocalRecommendationResponse | null;
  internet: InternetRecommendationResponse | null;
}
