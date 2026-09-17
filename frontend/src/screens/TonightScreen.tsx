import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  addDiscoveryToWatchLater,
  addInternetRecommendation,
  addTitleToWatchLater,
  dismissInternetRecommendation,
  dismissRecommendation,
  fetchMetadataReadiness,
  fetchRecommendationAgentStatus,
  recommendAgent,
  recommendInternet,
  recommendLocal,
  recordRecommendationFeedback,
  retryMetadataJobs,
  removeTitleFromWatchLater,
  startMetadataBackfill,
  updateTitle,
} from "../api";
import { ExternalIcon } from "../icons";
import type {
  AgentRecommendationResponse,
  DiscoveryResult,
  InternetRecommendationResponse,
  LocalRecommendationResponse,
  MetadataReadiness,
  RecommendationResult,
  RecommendationAgentStatus,
  RecommendationSeed,
} from "../types";

const BREAKDOWN_LABELS: Record<string, string> = {
  semantic_similarity: "Mood",
  taste_similarity: "Taste",
  feedback_match: "Learned",
  criteria_match: "Criteria",
  rating_quality: "Quality",
  priority_status: "Priority",
  novelty: "Novelty",
  context_fit: "Context",
  seed_similarity: "Taste",
  genre_keyword_match: "Prompt",
  metadata_quality: "Evidence",
};

type RecommendationMode = "local" | "internet" | "hybrid";
type ReasoningMode = "deterministic" | "gemini";
type RecommendationPayload = Parameters<typeof recommendLocal>[0];

const INITIAL_RESULT_LIMIT = 5;
const MAX_RESULT_LIMIT = 25;
const TONIGHT_SESSION_KEY = "whatch:tonight-session:v1";

const LANGUAGE_OPTIONS = [
  ["en", "English"],
  ["ar", "Arabic"],
  ["fr", "French"],
  ["es", "Spanish"],
  ["de", "German"],
  ["hi", "Hindi"],
  ["ja", "Japanese"],
  ["ko", "Korean"],
  ["tr", "Turkish"],
] as const;

const COUNTRY_OPTIONS = [
  ["US", "United States"],
  ["GB", "United Kingdom"],
  ["EG", "Egypt"],
  ["CA", "Canada"],
  ["FR", "France"],
  ["DE", "Germany"],
  ["IN", "India"],
  ["JP", "Japan"],
  ["KR", "South Korea"],
  ["TR", "Türkiye"],
] as const;

interface TonightSession {
  version: 1;
  mode: RecommendationMode;
  reasoning: ReasoningMode;
  prompt: string;
  mediaType: "either" | "movie" | "tv";
  runtimeMax: string;
  imdbMin: string;
  rtMin: string;
  genres: string;
  excludedGenres: string;
  genreMode: "prefer" | "require";
  releaseYearMode: "any" | "before" | "after";
  releaseYear: string;
  language: string;
  productionCountry: string;
  adventure: "safe" | "adjacent" | "adventurous";
  tone: "any" | "light" | "balanced" | "dark";
  pace: "any" | "relaxed" | "balanced" | "fast";
  company: "any" | "solo" | "group";
  strictMetadata: boolean;
  localResponse: LocalRecommendationResponse | null;
  internetResponse: InternetRecommendationResponse | null;
  agentResponse: AgentRecommendationResponse | null;
  resultLimit: number;
  advancedOpen: boolean;
  lastRequest: {
    mode: RecommendationMode;
    reasoning: ReasoningMode;
    payload: RecommendationPayload;
  } | null;
}

function readTonightSession(): TonightSession | null {
  try {
    const raw = window.sessionStorage.getItem(TONIGHT_SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as TonightSession;
    return value.version === 1 ? value : null;
  } catch {
    return null;
  }
}

function requestSignature(payload: RecommendationPayload) {
  const { limit: _limit, ...criteria } = payload;
  return JSON.stringify(criteria);
}

function AgentVerdict({
  reason,
  tradeoff,
}: {
  reason: string | null;
  tradeoff: string | null;
}) {
  if (!reason) return null;
  return (
    <div className="agent-verdict">
      <strong>Gemini’s take</strong>
      <p>{reason}</p>
      {tradeoff ? <small>Tradeoff: {tradeoff}</small> : null}
    </div>
  );
}

function ResultCard({
  result,
  sessionId,
  onRemove,
  featured = false,
  confidence,
  confidenceReason,
  onAnother,
  onWatchLaterChange,
}: {
  result: RecommendationResult;
  sessionId: number;
  onRemove: (id: number) => void;
  featured?: boolean;
  confidence?: LocalRecommendationResponse["confidence"];
  confidenceReason?: string;
  onAnother?: () => void;
  onWatchLaterChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<"watch" | "watch-later" | "dismiss" | "skip" | "preference" | null>(null);
  const [watchLater, setWatchLater] = useState(result.watch_later);
  const [preferenceSaved, setPreferenceSaved] = useState(false);
  const [awaitingRating, setAwaitingRating] = useState(false);
  const verifiedSource = result.links.find(({ domain }) =>
    [
      "justwatch",
      "netflix",
      "primevideo",
      "amazon",
      "disneyplus",
      "max.com",
      "hulu",
      "apple.com",
      "mubi",
      "criterion",
      "imdb",
      "themoviedb",
    ].some((provider) => domain.toLowerCase().includes(provider)),
  );
  const watchUrl = verifiedSource?.url
    ?? (result.imdb_id ? `https://www.imdb.com/title/${result.imdb_id}/` : null);

  async function markWatched() {
    setBusy("watch");
    try {
      await updateTitle(result.title_id, { status: "watched" });
      await recordRecommendationFeedback({
        session_id: sessionId,
        source: "local",
        action: "watched",
        media_item_id: result.title_id,
      }).catch(() => undefined);
      setAwaitingRating(true);
    } finally {
      setBusy(null);
    }
  }

  function record(action: Parameters<typeof recordRecommendationFeedback>[0]["action"]) {
    return recordRecommendationFeedback({
      session_id: sessionId,
      source: "local",
      action,
      media_item_id: result.title_id,
    }).catch(() => undefined);
  }

  async function notTonight() {
    setBusy("skip");
    try {
      await record("not_tonight");
      onRemove(result.title_id);
    } finally {
      setBusy(null);
    }
  }

  async function contextualSkip(action: "too_long" | "wrong_mood" | "seen_similar_recently") {
    setBusy("skip");
    try {
      await record(action);
      onRemove(result.title_id);
    } finally {
      setBusy(null);
    }
  }

  async function moreLikeThis() {
    await record("more_like_this");
    setPreferenceSaved(true);
  }

  async function lessLikeThis() {
    setBusy("preference");
    try {
      await record("less_like_this");
      onRemove(result.title_id);
    } finally {
      setBusy(null);
    }
  }

  async function finishRating(action: "liked" | "disliked" | null) {
    setBusy("preference");
    try {
      if (action) await record(action);
      onRemove(result.title_id);
    } finally {
      setBusy(null);
    }
  }

  async function dismiss() {
    setBusy("dismiss");
    try {
      await dismissRecommendation(result.title_id);
      await recordRecommendationFeedback({
        session_id: sessionId,
        source: "local",
        action: "dismissed",
        media_item_id: result.title_id,
      }).catch(() => undefined);
      onRemove(result.title_id);
    } finally {
      setBusy(null);
    }
  }

  async function toggleWatchLater() {
    setBusy("watch-later");
    try {
      if (watchLater) {
        await removeTitleFromWatchLater(result.title_id);
        setWatchLater(false);
      } else {
        await addTitleToWatchLater(result.title_id);
        setWatchLater(true);
      }
      await onWatchLaterChange();
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className={`recommendation-result ${featured ? "is-featured" : "is-alternative"}`}>
      {result.poster_url ? (
        <img className="recommendation-poster" src={result.poster_url} alt="" />
      ) : (
        <div className={`recommendation-poster poster-fallback cover-${result.title_id % 6}`}>
          {result.title.slice(0, 1)}
        </div>
      )}
      <div className="recommendation-copy">
        <div className="recommendation-title-line">
          <div>
            <h2>{result.title}</h2>
            <p>
              {result.media_type === "tv" ? "TV show" : "Movie"}
              {result.year ? ` · ${result.year}` : ""}
              {result.runtime_minutes ? ` · ${result.runtime_minutes} min` : ""}
              {result.original_language ? ` · ${result.original_language.toUpperCase()}` : ""}
              {result.production_countries?.length ? ` · ${result.production_countries.join(", ")}` : ""}
            </p>
          </div>
          <strong className="recommendation-score">
            {Math.round(result.score * 100)}
            <small>fit</small>
          </strong>
        </div>
        {featured ? (
          <div className="hero-ratings" aria-label="Ratings">
            <span>IMDb {result.imdb_rating?.toFixed(1) ?? "—"}</span>
            <span>
              Rotten Tomatoes{" "}
              {result.rotten_tomatoes_rating != null
                ? `${Math.round(result.rotten_tomatoes_rating)}%`
                : "—"}
            </span>
          </div>
        ) : null}
        {featured ? (
          <>
            <AgentVerdict reason={result.agent_reason} tradeoff={result.agent_tradeoff} />
            <section className="why-this-fits">
              <h3>Why this fits tonight</h3>
              <ul className="recommendation-reasons">
                {result.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </section>
            <div className="score-breakdown" aria-label="Score breakdown">
              {Object.entries(result.score_breakdown).map(([name, value]) => (
                <div key={name}>
                  <span>{BREAKDOWN_LABELS[name] ?? name}</span>
                  <i><b style={{ width: `${Math.min(100, value * 400)}%` }} /></i>
                </div>
              ))}
            </div>
          </>
        ) : null}
        {awaitingRating ? (
          <div className="recommendation-feedback-prompt" role="group" aria-label={`Rate ${result.title}`}>
            <strong>Did this recommendation work for you?</strong>
            <button type="button" onClick={() => finishRating("liked")} disabled={busy !== null}>
              Liked it
            </button>
            <button type="button" onClick={() => finishRating("disliked")} disabled={busy !== null}>
              Not for me
            </button>
            <button type="button" onClick={() => finishRating(null)} disabled={busy !== null}>
              Skip rating
            </button>
          </div>
        ) : (
        <div className="recommendation-actions">
          {watchUrl ? (
            <a
              className="primary-button"
              href={watchUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                void record("opened_watch_link");
                void record("selected");
              }}
            >
              {featured ? "Watch options" : "View title"}
              <ExternalIcon />
            </a>
          ) : null}
          {featured && onAnother ? (
            <button
              className="text-button"
              type="button"
              onClick={() => {
                void record("skipped");
                onAnother();
              }}
            >
              Another option
            </button>
          ) : null}
          <button
            className="text-button"
            type="button"
            onClick={toggleWatchLater}
            disabled={busy !== null}
          >
            {busy === "watch-later"
              ? "Updating…"
              : watchLater
                ? "Remove from Watch Later"
                : "Watch later"}
          </button>
          <button
            className="text-button"
            type="button"
            onClick={moreLikeThis}
            disabled={preferenceSaved}
          >
            {preferenceSaved ? "Preference saved" : "More like this"}
          </button>
          {featured ? (
            <button className="text-button" type="button" onClick={notTonight} disabled={busy !== null}>
              {busy === "skip" ? "Skipping…" : "Not tonight"}
            </button>
          ) : null}
          <details className="feedback-reasons">
            <summary>Why not?</summary>
            <div>
              <button type="button" onClick={() => contextualSkip("too_long")} disabled={busy !== null}>Too long tonight</button>
              <button type="button" onClick={() => contextualSkip("wrong_mood")} disabled={busy !== null}>Wrong mood</button>
              <button type="button" onClick={() => contextualSkip("seen_similar_recently")} disabled={busy !== null}>Too similar lately</button>
            </div>
          </details>
          <button className="text-button" type="button" onClick={lessLikeThis} disabled={busy !== null}>
            {busy === "preference" ? "Saving…" : "Less like this"}
          </button>
          <button className="text-button" onClick={markWatched} disabled={busy !== null}>
            {busy === "watch" ? "Updating…" : "Mark watched"}
          </button>
          <button className="text-button" onClick={dismiss} disabled={busy !== null}>
            {busy === "dismiss" ? "Dismissing…" : "Not interested"}
          </button>
        </div>
        )}
        {featured && confidence ? (
          <div className={`hero-confidence confidence-${confidence}`}>
            <strong>{confidence} confidence</strong>
            <p>{confidenceReason}</p>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function DiscoveryCard({
  result,
  sessionId,
  onRemove,
  featured = false,
  confidence,
  onAnother,
  onWatchLaterChange,
}: {
  result: DiscoveryResult;
  sessionId: number;
  onRemove: (result: DiscoveryResult) => void;
  featured?: boolean;
  confidence?: InternetRecommendationResponse["confidence"];
  onAnother?: () => void;
  onWatchLaterChange: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<"add" | "watch" | "watch-later" | "dismiss" | "skip" | "preference" | null>(null);
  const [addedMediaId, setAddedMediaId] = useState<number | null>(null);
  const [watchLater, setWatchLater] = useState(false);
  const [awaitingRating, setAwaitingRating] = useState(false);
  const [preferenceSaved, setPreferenceSaved] = useState(false);

  function record(
    action: Parameters<typeof recordRecommendationFeedback>[0]["action"],
    mediaItemId?: number,
  ) {
    return recordRecommendationFeedback({
      session_id: sessionId,
      source: "internet",
      action,
      media_item_id: mediaItemId,
      candidate_id: result.candidate_id,
    }).catch(() => undefined);
  }

  async function addToLibrary() {
    setBusy("add");
    try {
      const addedResult = await addInternetRecommendation(result.candidate_id);
      await recordRecommendationFeedback({
        session_id: sessionId,
        source: "internet",
        action: "added",
        media_item_id: addedResult.media_item_id,
        candidate_id: result.candidate_id,
      }).catch(() => undefined);
      setAddedMediaId(addedResult.media_item_id);
    } finally {
      setBusy(null);
    }
  }

  async function toggleWatchLater() {
    setBusy("watch-later");
    try {
      if (watchLater && addedMediaId) {
        await removeTitleFromWatchLater(addedMediaId);
        setWatchLater(false);
      } else if (addedMediaId) {
        await addTitleToWatchLater(addedMediaId);
        setWatchLater(true);
      } else {
        const added = await addDiscoveryToWatchLater(result.candidate_id);
        setAddedMediaId(added.id);
        setWatchLater(true);
        await record("added", added.id);
      }
      await onWatchLaterChange();
    } finally {
      setBusy(null);
    }
  }

  async function dismiss() {
    setBusy("dismiss");
    try {
      await dismissInternetRecommendation(result.media_type, result.tmdb_id);
      await recordRecommendationFeedback({
        session_id: sessionId,
        source: "internet",
        action: "dismissed",
        candidate_id: result.candidate_id,
      }).catch(() => undefined);
      onRemove(result);
    } finally {
      setBusy(null);
    }
  }

  async function notTonight() {
    setBusy("skip");
    try {
      await record("not_tonight");
      onRemove(result);
    } finally {
      setBusy(null);
    }
  }

  async function contextualSkip(action: "too_long" | "wrong_mood" | "seen_similar_recently") {
    setBusy("skip");
    try {
      await record(action);
      onRemove(result);
    } finally {
      setBusy(null);
    }
  }

  async function moreLikeThis() {
    await record("more_like_this");
    setPreferenceSaved(true);
  }

  async function lessLikeThis() {
    setBusy("preference");
    try {
      await record("less_like_this", addedMediaId ?? undefined);
      onRemove(result);
    } finally {
      setBusy(null);
    }
  }

  async function markDiscoveryWatched() {
    if (!addedMediaId) return;
    setBusy("watch");
    try {
      await updateTitle(addedMediaId, { status: "watched" });
      await record("watched", addedMediaId);
      setAwaitingRating(true);
    } finally {
      setBusy(null);
    }
  }

  async function finishRating(action: "liked" | "disliked" | null) {
    setBusy("preference");
    try {
      if (action) await record(action, addedMediaId ?? undefined);
      onRemove(result);
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className={`recommendation-result discovery-result ${featured ? "is-featured" : "is-alternative"}`}>
      {result.poster_url ? (
        <img className="recommendation-poster" src={result.poster_url} alt="" />
      ) : (
        <div className={`recommendation-poster poster-fallback cover-${result.tmdb_id % 6}`}>
          {result.title.slice(0, 1)}
        </div>
      )}
      <div className="recommendation-copy">
        <div className="discovery-source">Internet discovery</div>
        <div className="recommendation-title-line">
          <div>
            <h2>{result.title}</h2>
            <p>
              {result.media_type === "tv" ? "TV show" : "Movie"}
              {result.year ? ` · ${result.year}` : ""}
              {result.runtime_minutes ? ` · ${result.runtime_minutes} min` : ""}
              {result.original_language ? ` · ${result.original_language.toUpperCase()}` : ""}
              {result.production_countries?.length ? ` · ${result.production_countries.join(", ")}` : ""}
              {result.imdb_rating ? ` · IMDb ${result.imdb_rating}` : ""}
              {result.rotten_tomatoes_rating
                ? ` · RT ${result.rotten_tomatoes_rating}%`
                : ""}
            </p>
          </div>
          <strong className="recommendation-score">
            {Math.round(result.score * 100)}
            <small>fit</small>
          </strong>
        </div>
        {featured ? (
          <div className="hero-ratings" aria-label="Ratings">
            <span>IMDb {result.imdb_rating?.toFixed(1) ?? "—"}</span>
            <span>
              Rotten Tomatoes{" "}
              {result.rotten_tomatoes_rating != null
                ? `${Math.round(result.rotten_tomatoes_rating)}%`
                : "—"}
            </span>
          </div>
        ) : null}
        {featured ? (
          <>
            {result.overview ? <p className="discovery-overview">{result.overview}</p> : null}
            <AgentVerdict reason={result.agent_reason} tradeoff={result.agent_tradeoff} />
            <section className="why-this-fits">
              <h3>Why this fits tonight</h3>
              <ul className="recommendation-reasons">
                {result.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </section>
            <div className="score-breakdown" aria-label="Score breakdown">
              {Object.entries(result.score_breakdown).map(([name, value]) => (
                <div key={name}>
                  <span>{BREAKDOWN_LABELS[name] ?? name}</span>
                  <i><b style={{ width: `${Math.min(100, value * 400)}%` }} /></i>
                </div>
              ))}
            </div>
          </>
        ) : null}
        {awaitingRating ? (
          <div className="recommendation-feedback-prompt" role="group" aria-label={`Rate ${result.title}`}>
            <strong>Did this recommendation work for you?</strong>
            <button type="button" onClick={() => finishRating("liked")} disabled={busy !== null}>
              Liked it
            </button>
            <button type="button" onClick={() => finishRating("disliked")} disabled={busy !== null}>
              Not for me
            </button>
            <button type="button" onClick={() => finishRating(null)} disabled={busy !== null}>
              Skip rating
            </button>
          </div>
        ) : (
        <div className="recommendation-actions">
          <a
            className="primary-button"
            href={result.tmdb_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => {
              void record("opened_watch_link");
              void record("selected");
            }}
          >
            {featured ? "Watch options" : "View on TMDB"}
            <ExternalIcon />
          </a>
          {featured && onAnother ? (
            <button
              className="text-button"
              type="button"
              onClick={() => {
                void record("skipped");
                onAnother();
              }}
            >
              Another option
            </button>
          ) : null}
          <button
            className="text-button"
            type="button"
            onClick={toggleWatchLater}
            disabled={busy !== null}
          >
            {busy === "watch-later"
              ? "Updating…"
              : watchLater
                ? "Remove from Watch Later"
                : "Watch later"}
          </button>
          <button
            className="text-button"
            type="button"
            onClick={moreLikeThis}
            disabled={preferenceSaved}
          >
            {preferenceSaved ? "Preference saved" : "More like this"}
          </button>
          {featured ? (
            <button className="text-button" type="button" onClick={notTonight} disabled={busy !== null}>
              {busy === "skip" ? "Skipping…" : "Not tonight"}
            </button>
          ) : null}
          <details className="feedback-reasons">
            <summary>Why not?</summary>
            <div>
              <button type="button" onClick={() => contextualSkip("too_long")} disabled={busy !== null}>Too long tonight</button>
              <button type="button" onClick={() => contextualSkip("wrong_mood")} disabled={busy !== null}>Wrong mood</button>
              <button type="button" onClick={() => contextualSkip("seen_similar_recently")} disabled={busy !== null}>Too similar lately</button>
            </div>
          </details>
          <button className="text-button" type="button" onClick={lessLikeThis} disabled={busy !== null}>
            {busy === "preference" ? "Saving…" : "Less like this"}
          </button>
          <button
            className="text-button"
            onClick={addToLibrary}
            disabled={busy !== null || addedMediaId !== null}
          >
            {busy === "add" ? "Adding…" : addedMediaId ? "Added to library" : "Add to library"}
          </button>
          {addedMediaId ? (
            <button className="text-button" type="button" onClick={markDiscoveryWatched} disabled={busy !== null}>
              {busy === "watch" ? "Updating…" : "Mark watched"}
            </button>
          ) : null}
          <button className="text-button" onClick={dismiss} disabled={busy !== null}>
            {busy === "dismiss" ? "Dismissing…" : "Not interested"}
          </button>
        </div>
        )}
        {featured && confidence ? (
          <div className={`hero-confidence confidence-${confidence}`}>
            <strong>{confidence} confidence</strong>
            <p>
              Online candidates are ranked against your mood, constraints, ratings,
              and saved taste profile.
            </p>
          </div>
        ) : null}
      </div>
    </article>
  );
}

interface TonightScreenProps {
  seedTitles: RecommendationSeed[];
  onClearSeeds: () => void;
  onWatchLaterChange: () => Promise<void>;
}

export function TonightScreen({
  seedTitles,
  onClearSeeds,
  onWatchLaterChange,
}: TonightScreenProps) {
  const [restored] = useState(readTonightSession);
  const [mode, setMode] = useState<RecommendationMode>(
    seedTitles.length ? "internet" : restored?.mode ?? "hybrid",
  );
  const [reasoning, setReasoning] = useState<ReasoningMode>(restored?.reasoning ?? "deterministic");
  const [prompt, setPrompt] = useState(restored?.prompt ?? "");
  const [mediaType, setMediaType] = useState<"either" | "movie" | "tv">(restored?.mediaType ?? "movie");
  const [runtimeMax, setRuntimeMax] = useState(restored?.runtimeMax ?? "120");
  const [imdbMin, setImdbMin] = useState(restored?.imdbMin ?? "6.5");
  const [rtMin, setRtMin] = useState(restored?.rtMin ?? "");
  const [genres, setGenres] = useState(restored?.genres ?? "");
  const [excludedGenres, setExcludedGenres] = useState(restored?.excludedGenres ?? "");
  const [genreMode, setGenreMode] = useState<"prefer" | "require">(restored?.genreMode ?? "prefer");
  const [releaseYearMode, setReleaseYearMode] = useState<"any" | "before" | "after">(
    restored?.releaseYearMode ?? "any",
  );
  const [releaseYear, setReleaseYear] = useState(restored?.releaseYear ?? "");
  const [language, setLanguage] = useState(restored?.language ?? "");
  const [productionCountry, setProductionCountry] = useState(
    restored?.productionCountry ?? "",
  );
  const [adventure, setAdventure] = useState<"safe" | "adjacent" | "adventurous">(restored?.adventure ?? "adjacent");
  const [tone, setTone] = useState<"any" | "light" | "balanced" | "dark">(restored?.tone ?? "any");
  const [pace, setPace] = useState<"any" | "relaxed" | "balanced" | "fast">(restored?.pace ?? "any");
  const [company, setCompany] = useState<"any" | "solo" | "group">(restored?.company ?? "any");
  const [strictMetadata, setStrictMetadata] = useState(restored?.strictMetadata ?? false);
  const [localResponse, setLocalResponse] = useState<LocalRecommendationResponse | null>(restored?.localResponse ?? null);
  const [internetResponse, setInternetResponse] =
    useState<InternetRecommendationResponse | null>(restored?.internetResponse ?? null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [resultLimit, setResultLimit] = useState(restored?.resultLimit ?? INITIAL_RESULT_LIMIT);
  const [error, setError] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<MetadataReadiness | null>(null);
  const [agentStatus, setAgentStatus] = useState<RecommendationAgentStatus | null>(null);
  const [agentResponse, setAgentResponse] = useState<AgentRecommendationResponse | null>(restored?.agentResponse ?? null);
  const [backfilling, setBackfilling] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(restored?.advancedOpen ?? false);
  const recordedImpressions = useRef(new Set<string>());
  const lastRequest = useRef<{
    mode: RecommendationMode;
    reasoning: ReasoningMode;
    payload: RecommendationPayload;
  } | null>(restored?.lastRequest ?? null);

  useEffect(() => {
    let active = true;
    fetchMetadataReadiness()
      .then((value) => active && setReadiness(value))
      .catch(() => undefined);
    fetchRecommendationAgentStatus()
      .then((value) => active && setAgentStatus(value))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!readiness || readiness.queued + readiness.running === 0) return;
    let active = true;
    const timer = window.setTimeout(() => {
      fetchMetadataReadiness()
        .then((value) => active && setReadiness(value))
        .catch(() => undefined);
    }, 1200);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [readiness]);

  function buildPayload(limit: number): RecommendationPayload {
    return {
      prompt: prompt.trim() || undefined,
      media_type: mediaType,
      runtime_max: runtimeMax ? Number(runtimeMax) : undefined,
      imdb_min: imdbMin ? Number(imdbMin) : undefined,
      rt_min: rtMin ? Number(rtMin) : undefined,
      genres: genres.split(",").map((genre) => genre.trim()).filter(Boolean),
      excluded_genres: excludedGenres.split(",").map((genre) => genre.trim()).filter(Boolean),
      genre_mode: genreMode,
      release_year_mode: releaseYear ? releaseYearMode : "any",
      release_year: releaseYear ? Number(releaseYear) : undefined,
      language: language || undefined,
      production_country: productionCountry || undefined,
      seed_title_ids: seedTitles.map((title) => title.id),
      adventure,
      tone,
      pace,
      company,
      strict_metadata: strictMetadata,
      limit,
    };
  }

  const currentCriteriaSignature = requestSignature(buildPayload(INITIAL_RESULT_LIMIT));

  useEffect(() => {
    const request = lastRequest.current;
    if (
      !request
      || (
        request.mode === mode
        && request.reasoning === reasoning
        && requestSignature(request.payload) === currentCriteriaSignature
      )
    ) {
      return;
    }
    lastRequest.current = null;
    setLocalResponse(null);
    setInternetResponse(null);
    setAgentResponse(null);
    setResultLimit(INITIAL_RESULT_LIMIT);
    recordedImpressions.current.clear();
  }, [currentCriteriaSignature, mode, reasoning]);

  useEffect(() => {
    const value: TonightSession = {
      version: 1,
      mode,
      reasoning,
      prompt,
      mediaType,
      runtimeMax,
      imdbMin,
      rtMin,
      genres,
      excludedGenres,
      genreMode,
      releaseYearMode,
      releaseYear,
      language,
      productionCountry,
      adventure,
      tone,
      pace,
      company,
      strictMetadata,
      localResponse,
      internetResponse,
      agentResponse,
      resultLimit,
      advancedOpen,
      lastRequest: lastRequest.current,
    };
    try {
      window.sessionStorage.setItem(TONIGHT_SESSION_KEY, JSON.stringify(value));
    } catch {
      // Session persistence is a convenience; recommendations still work in memory.
    }
  }, [
    advancedOpen,
    adventure,
    agentResponse,
    company,
    genres,
    excludedGenres,
    genreMode,
    releaseYearMode,
    releaseYear,
    language,
    productionCountry,
    imdbMin,
    internetResponse,
    localResponse,
    mediaType,
    mode,
    pace,
    prompt,
    reasoning,
    resultLimit,
    rtMin,
    runtimeMax,
    strictMetadata,
    tone,
  ]);

  async function runRecommendations(
    payload: RecommendationPayload,
    requestMode: RecommendationMode,
    requestReasoning: ReasoningMode,
  ) {
    if (requestReasoning === "gemini") {
      const response = await recommendAgent({
        ...payload,
        scope: requestMode,
        cloud_consent: true,
      });
      setAgentResponse(response);
      setLocalResponse(response.local);
      setInternetResponse(response.internet);
      return;
    }
    setAgentResponse(null);
    if (requestMode === "local") {
      setLocalResponse(await recommendLocal(payload));
      setInternetResponse(null);
    } else if (requestMode === "internet") {
      setInternetResponse(await recommendInternet(payload));
      setLocalResponse(null);
    } else {
      const [local, internet] = await Promise.all([
        recommendLocal(payload),
        recommendInternet(payload),
      ]);
      setLocalResponse(local);
      setInternetResponse(internet);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    const payload = buildPayload(INITIAL_RESULT_LIMIT);
    lastRequest.current = { mode, reasoning, payload };
    try {
      await runRecommendations(payload, mode, reasoning);
      setResultLimit(INITIAL_RESULT_LIMIT);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not generate recommendations");
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (!lastRequest.current || loadingMore) return;
    const nextLimit = Math.min(MAX_RESULT_LIMIT, resultLimit + INITIAL_RESULT_LIMIT);
    const request = lastRequest.current;
    const payload = { ...request.payload, limit: nextLimit };
    setLoadingMore(true);
    setError(null);
    try {
      await runRecommendations(payload, request.mode, request.reasoning);
      lastRequest.current = { ...request, payload };
      setResultLimit(nextLimit);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load more recommendations");
    } finally {
      setLoadingMore(false);
    }
  }

  function removeResult(id: number) {
    setLocalResponse((current) =>
      current
        ? { ...current, results: current.results.filter((result) => result.title_id !== id) }
        : current,
    );
  }

  function removeDiscovery(result: DiscoveryResult) {
    setInternetResponse((current) =>
      current
        ? {
            ...current,
            results: current.results.filter(
              (candidate) =>
                candidate.tmdb_id !== result.tmdb_id
                || candidate.media_type !== result.media_type,
            ),
          }
        : current,
    );
  }

  async function runBackfill(retry = false) {
    setBackfilling(true);
    setError(null);
    try {
      const result = retry
        ? await retryMetadataJobs(5)
        : await startMetadataBackfill(5);
      setReadiness(result.readiness);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start metadata batch");
    } finally {
      setBackfilling(false);
    }
  }

  const hasUnloadedResults = (
    Boolean(
      localResponse
      && localResponse.results.length > 0
      && localResponse.results.length < localResponse.candidate_count,
    )
    || Boolean(
      internetResponse
      && internetResponse.results.length > 0
      && internetResponse.results.length < internetResponse.candidate_count,
    )
  );
  const loadedResultCount = (localResponse?.results.length ?? 0)
    + (internetResponse?.results.length ?? 0);
  const availableResultCount = (localResponse?.candidate_count ?? 0)
    + (internetResponse?.candidate_count ?? 0);
  const reachedResultLimit = resultLimit >= MAX_RESULT_LIMIT;
  const canLoadMore = hasUnloadedResults && !reachedResultLimit;
  const showLoadMore = lastRequest.current !== null && loadedResultCount > 0;
  const loadMoreLabel = reachedResultLimit
    ? `Maximum ${MAX_RESULT_LIMIT} loaded per source`
    : !hasUnloadedResults
      ? "All matching options loaded"
      : lastRequest.current?.mode === "hybrid"
        ? "Load 5 more from each source"
        : "Load 5 more";

  function rotateLocalResults() {
    setLocalResponse((current) => current && current.results.length > 1
      ? { ...current, results: [...current.results.slice(1), current.results[0]] }
      : current);
  }

  function rotateInternetResults() {
    setInternetResponse((current) => current && current.results.length > 1
      ? { ...current, results: [...current.results.slice(1), current.results[0]] }
      : current);
  }

  useEffect(() => {
    const feedback: Array<Parameters<typeof recordRecommendationFeedback>[0]> = [];
    if (localResponse) {
      const sessionId = agentResponse?.session_id ?? localResponse.session_id;
      for (const result of localResponse.results) {
        const key = `${sessionId}:local:${result.title_id}`;
        if (recordedImpressions.current.has(key)) continue;
        recordedImpressions.current.add(key);
        feedback.push({
          session_id: sessionId,
          source: "local",
          action: "impression",
          media_item_id: result.title_id,
        });
      }
    }
    if (internetResponse) {
      const sessionId = agentResponse?.session_id ?? internetResponse.session_id;
      for (const result of internetResponse.results) {
        const key = `${sessionId}:internet:${result.candidate_id}`;
        if (recordedImpressions.current.has(key)) continue;
        recordedImpressions.current.add(key);
        feedback.push({
          session_id: sessionId,
          source: "internet",
          action: "impression",
          candidate_id: result.candidate_id,
        });
      }
    }
    if (feedback.length) {
      void Promise.all(
        feedback.map((payload) =>
          Promise.resolve(recordRecommendationFeedback(payload)).catch(() => undefined),
        ),
      );
    }
  }, [agentResponse?.session_id, internetResponse, localResponse]);

  const hasResults = Boolean(localResponse || internetResponse);

  return (
    <main className="tonight-screen">
      <header className="tonight-header">
        <h1>What fits tonight?</h1>
        <p>A better pick for your mood and time.</p>
      </header>
      <form className={`tonight-criteria ${hasResults ? "has-results" : ""}`} onSubmit={submit}>
        <div className="tonight-query-bar">
          <label className="mood-query">
            <span className="sr-only">What are you in the mood for?</span>
            <input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Dark and cerebral, but not exhausting…"
              maxLength={1000}
            />
          </label>
          <label className="quick-constraint">
            <span>Type</span>
            <select
              value={mediaType}
              onChange={(event) => setMediaType(event.target.value as typeof mediaType)}
              aria-label="Media type"
            >
              <option value="either">Movie or TV</option>
              <option value="movie">Movie</option>
              <option value="tv">TV show</option>
            </select>
          </label>
          <label className="quick-constraint">
            <span>Runtime</span>
            <select
              value={runtimeMax}
              onChange={(event) => setRuntimeMax(event.target.value)}
              aria-label="Maximum runtime"
            >
              <option value="">Any runtime</option>
              <option value="90">Under 90 min</option>
              <option value="105">Under 105 min</option>
              <option value="120">Under 2 hours</option>
              <option value="150">Under 2½ hours</option>
            </select>
          </label>
          <label className="quick-constraint">
            <span>Sources</span>
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as RecommendationMode)}
              aria-label="Recommendation sources"
            >
              <option value="local">My list</option>
              <option value="internet">Internet</option>
              <option value="hybrid">Both sources</option>
            </select>
          </label>
          <button
            className="primary-button tonight-submit"
            type="submit"
            disabled={loading || loadingMore}
          >
            {loading ? "Finding your best fit…" : "Find something to watch"}
          </button>
        </div>
        <button
          className="more-options-toggle"
          type="button"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((current) => !current)}
        >
          {advancedOpen ? "Fewer options" : "More options"}
        </button>
        {advancedOpen ? (
          <div className="tonight-advanced">
            <fieldset className="recommendation-mode reasoning-mode">
              <legend>Reasoning</legend>
              <div>
                <button
                  className={reasoning === "deterministic" ? "is-active" : ""}
                  type="button"
                  aria-pressed={reasoning === "deterministic"}
                  onClick={() => setReasoning("deterministic")}
                >
                  Local ranker
                </button>
                <button
                  className={reasoning === "gemini" ? "is-active" : ""}
                  type="button"
                  aria-pressed={reasoning === "gemini"}
                  onClick={() => setReasoning("gemini")}
                  disabled={!agentStatus?.available}
                >
                  Gemini agent
                </button>
              </div>
              <small>
                {reasoning === "gemini" && agentStatus
                  ? agentStatus.privacy_summary
                  : agentStatus?.available
                    ? "Use fast local scoring, or Gemini for a final cross-source judgment."
                    : agentStatus?.configured && !agentStatus.enabled
                      ? "Gemini is configured but disabled."
                      : "Gemini becomes available after its API key is configured and enabled."}
              </small>
            </fieldset>
          <fieldset className="tonight-context">
            <legend>Tonight context</legend>
            <div className="context-control">
              <span>Tone</span>
              <div>
                {(["any", "light", "balanced", "dark"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={tone === value ? "is-active" : ""}
                    aria-pressed={tone === value}
                    onClick={() => setTone(value)}
                  >
                    {value === "any" ? "Any" : value}
                  </button>
                ))}
              </div>
            </div>
            <div className="context-control">
              <span>Pace</span>
              <div>
                {(["any", "relaxed", "balanced", "fast"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={pace === value ? "is-active" : ""}
                    aria-pressed={pace === value}
                    onClick={() => setPace(value)}
                  >
                    {value === "any" ? "Any" : value}
                  </button>
                ))}
              </div>
            </div>
            <div className="context-control">
              <span>Company</span>
              <div>
                {(["any", "solo", "group"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={company === value ? "is-active" : ""}
                    aria-pressed={company === value}
                    onClick={() => setCompany(value)}
                  >
                    {value === "any" ? "Any" : value}
                  </button>
                ))}
              </div>
            </div>
            <small>These are soft preferences. Runtime, type, required genres, and exclusions are hard constraints.</small>
          </fieldset>
          {seedTitles.length ? (
            <section className="similarity-seeds">
              <div>
                <strong>Similarity seeds</strong>
                <button className="text-button" type="button" onClick={onClearSeeds}>
                  Clear
                </button>
              </div>
              <ul>
                {seedTitles.map((title) => (
                  <li key={title.id}>
                    {title.title}{title.year ? ` (${title.year})` : ""}
                  </li>
                ))}
              </ul>
              <small>
                Provider discovery and local ranking will anchor similarity to these
                selected titles.
              </small>
            </section>
          ) : null}
          <div className="advanced-fields">
            <label>
              <span>Minimum IMDb</span>
              <select value={imdbMin} onChange={(event) => setImdbMin(event.target.value)}>
                <option value="">No minimum</option>
                <option value="6">6.0+</option>
                <option value="6.5">6.5+</option>
                <option value="7">7.0+</option>
                <option value="7.5">7.5+</option>
                <option value="8">8.0+</option>
              </select>
            </label>
            <label>
              <span>Minimum RT</span>
              <select value={rtMin} onChange={(event) => setRtMin(event.target.value)}>
                <option value="">No minimum</option>
                <option value="60">60%+</option>
                <option value="70">70%+</option>
                <option value="80">80%+</option>
                <option value="90">90%+</option>
              </select>
            </label>
            <label>
              <span>Preferred genres</span>
              <input
                value={genres}
                onChange={(event) => setGenres(event.target.value)}
                placeholder="thriller, drama"
              />
            </label>
            <label>
              <span>Genre handling</span>
              <select value={genreMode} onChange={(event) => setGenreMode(event.target.value as typeof genreMode)}>
                <option value="prefer">Prefer, allow adjacent</option>
                <option value="require">Require at least one</option>
              </select>
            </label>
            <label>
              <span>Exclude genres</span>
              <input
                value={excludedGenres}
                onChange={(event) => setExcludedGenres(event.target.value)}
                placeholder="horror, musical"
              />
            </label>
            <label>
              <span>Release year</span>
              <span className="year-constraint">
                <select
                  aria-label="Release year direction"
                  value={releaseYearMode}
                  onChange={(event) => setReleaseYearMode(event.target.value as typeof releaseYearMode)}
                >
                  <option value="any">Any year</option>
                  <option value="before">Before</option>
                  <option value="after">After</option>
                </select>
                <input
                  aria-label="Release year"
                  type="number"
                  min="1888"
                  max="2100"
                  value={releaseYear}
                  onChange={(event) => setReleaseYear(event.target.value)}
                  placeholder="1995"
                  disabled={releaseYearMode === "any"}
                />
              </span>
            </label>
            <label>
              <span>Discovery style</span>
              <select value={adventure} onChange={(event) => setAdventure(event.target.value as typeof adventure)}>
                <option value="safe">Safe and highly rated</option>
                <option value="adjacent">Adjacent to your taste</option>
                <option value="adventurous">More adventurous</option>
              </select>
            </label>
            <label>
              <span>Original language</span>
              <input
                aria-label="Original language"
                list="tonight-language-options"
                value={language}
                onChange={(event) => setLanguage(event.target.value.toLowerCase())}
                placeholder="Any · e.g. ar"
                maxLength={3}
                pattern="[A-Za-z]{2,3}"
                title="Use a 2- or 3-letter language code"
              />
              <datalist id="tonight-language-options">
                {LANGUAGE_OPTIONS.map(([code, name]) => (
                  <option key={code} value={code} label={name} />
                ))}
              </datalist>
            </label>
            <label>
              <span>Production country</span>
              <input
                aria-label="Production country"
                list="tonight-country-options"
                value={productionCountry}
                onChange={(event) => setProductionCountry(event.target.value.toUpperCase())}
                placeholder="Any · e.g. EG"
                maxLength={2}
                pattern="[A-Za-z]{2}"
                title="Use a 2-letter country code"
              />
              <datalist id="tonight-country-options">
                {COUNTRY_OPTIONS.map(([code, name]) => (
                  <option key={code} value={code} label={name} />
                ))}
              </datalist>
            </label>
            <label className="metadata-strictness">
              <span>Missing metadata</span>
              <span className="checkbox-label">
                <input
                  type="checkbox"
                  checked={strictMetadata}
                  onChange={(event) => setStrictMetadata(event.target.checked)}
                />
                Require known ratings and runtime
              </span>
            </label>
          </div>
          {readiness ? (
            <section className="readiness-panel">
              <div className="readiness-heading">
                <strong>Recommendation data</strong>
                <span>{readiness.enriched} / {readiness.eligible}</span>
              </div>
              <div className="readiness-progress">
                <i
                  style={{
                    width: `${readiness.eligible
                      ? readiness.enriched / readiness.eligible * 100
                      : 0}%`,
                  }}
                />
              </div>
              <p>
                {readiness.overview} descriptions · {readiness.genres} genres ·{" "}
                {readiness.runtime} runtimes
              </p>
              {readiness.queued + readiness.running > 0 ? (
                <small>
                  {readiness.running} running · {readiness.queued} queued
                </small>
              ) : (
                <button
                  className="text-button"
                  type="button"
                  onClick={() => runBackfill(false)}
                  disabled={backfilling || readiness.enriched >= readiness.eligible}
                >
                  {backfilling ? "Starting…" : "Enrich next 5"}
                </button>
              )}
              {readiness.failed > 0 && readiness.queued + readiness.running === 0 ? (
                <button
                  className="text-button"
                  type="button"
                  onClick={() => runBackfill(true)}
                  disabled={backfilling}
                >
                  Retry failed ({readiness.failed})
                </button>
              ) : null}
            </section>
          ) : null}
          </div>
        ) : null}
      </form>
      <section className="tonight-results" aria-live="polite">
          {error ? <div className="inline-error">{error}</div> : null}
          {agentResponse ? (
            <section className="agent-summary">
              <div>
                <span>
                  {agentResponse.provider === "gemini"
                    ? `Gemini agent · ${agentResponse.model}`
                    : "Local fallback"}
                </span>
                <p>{agentResponse.summary}</p>
              </div>
              {agentResponse.interpreted_preferences.length ? (
                <ul>
                  {agentResponse.interpreted_preferences.map((preference) => (
                    <li key={preference}>{preference}</li>
                  ))}
                </ul>
              ) : null}
              {agentResponse.search_plan?.queries.length ? (
                <div className="agent-search-evidence">
                  <strong>Provider searches</strong>
                  <p>{agentResponse.search_plan.queries.join(" · ")}</p>
                </div>
              ) : null}
              {agentResponse.fallback_reason ? (
                <small>{agentResponse.fallback_reason}</small>
              ) : null}
            </section>
          ) : null}
          {!localResponse && !internetResponse && !loading ? (
            <div className="tonight-empty">
              <h2>Your shortlist will appear here.</h2>
              <p>
                Describe the evening in one line. Whatch will compare your library
                with online discoveries and explain the strongest fit.
              </p>
            </div>
          ) : null}
          {localResponse ? (
            <section className="result-group">
              {mode === "hybrid" ? (
                <div className="result-group-heading">
                  <span>From your list</span>
                  <p>Already saved locally and ready to choose.</p>
                </div>
              ) : null}
              {localResponse.results.length ? (
                <>
                  <ResultCard
                    result={localResponse.results[0]}
                    sessionId={agentResponse?.session_id ?? localResponse.session_id}
                    onRemove={removeResult}
                    featured
                    confidence={localResponse.confidence}
                    confidenceReason={localResponse.confidence_reason}
                    onAnother={rotateLocalResults}
                    onWatchLaterChange={onWatchLaterChange}
                  />
                  {localResponse.results.length > 1 ? (
                    <div className="alternatives-section">
                      <div className="alternatives-heading">
                        <h2>More to consider</h2>
                        <span />
                      </div>
                      <div className="alternative-grid">
                        {localResponse.results.slice(1).map((result) => (
                          <ResultCard
                            key={result.title_id}
                            result={result}
                            sessionId={agentResponse?.session_id ?? localResponse.session_id}
                            onRemove={removeResult}
                            onWatchLaterChange={onWatchLaterChange}
                          />
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="tonight-empty compact">
                  <h2>No titles fit every constraint.</h2>
                  <p>Remove a rating, genre, or runtime limit and try again.</p>
                </div>
              )}
            </section>
          ) : null}
          {internetResponse ? (
            <section className="result-group">
              {mode === "hybrid" ? (
                <div className="result-group-heading">
                  <span>New discoveries</span>
                  <p>Not in your catalog; sourced from TMDB and enriched by OMDb.</p>
                </div>
              ) : null}
              {internetResponse.results.length ? (
                <>
                  <DiscoveryCard
                    result={internetResponse.results[0]}
                    sessionId={agentResponse?.session_id ?? internetResponse.session_id}
                    onRemove={removeDiscovery}
                    featured
                    confidence={internetResponse.confidence}
                    onAnother={rotateInternetResults}
                    onWatchLaterChange={onWatchLaterChange}
                  />
                  {internetResponse.results.length > 1 ? (
                    <div className="alternatives-section">
                      <div className="alternatives-heading">
                        <h2>More to consider</h2>
                        <span />
                      </div>
                      <div className="alternative-grid">
                        {internetResponse.results.slice(1).map((result) => (
                          <DiscoveryCard
                            key={`${result.media_type}-${result.tmdb_id}`}
                            result={result}
                            sessionId={agentResponse?.session_id ?? internetResponse.session_id}
                            onRemove={removeDiscovery}
                            onWatchLaterChange={onWatchLaterChange}
                          />
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="tonight-empty compact">
                  <h2>No new titles fit every constraint.</h2>
                  <p>Remove a rating, genre, or runtime limit and search again.</p>
                </div>
              )}
            </section>
          ) : null}
          {showLoadMore ? (
            <div className="load-more-recommendations">
              <button
                className="primary-button"
                type="button"
                onClick={loadMore}
                disabled={loadingMore || loading || !canLoadMore}
              >
                {loadingMore ? "Loading more…" : loadMoreLabel}
              </button>
              <small>
                {loadedResultCount} loaded
                {availableResultCount > loadedResultCount
                  ? ` · ${availableResultCount - loadedResultCount} matching options remain`
                  : " · complete"}
                {" "}· up to {MAX_RESULT_LIMIT} per source with the same criteria.
              </small>
            </div>
          ) : null}
      </section>
    </main>
  );
}
