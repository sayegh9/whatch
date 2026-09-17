# Whatch

Whatch is a private, local-first movie and TV catalog. It imports the existing
Markdown bookmark list, preserves every actionable source link, merges exact
IMDb duplicates, and keeps ambiguous rows in a review queue.

## Run locally

### Double-click on macOS

Open `Start Whatch.command` from Finder. It prepares an updated frontend build
when necessary, applies pending database migrations, starts the private local
server, and opens Whatch automatically.
Keep its Terminal window open while using the app; close it or press Control-C
to stop Whatch. Startup diagnostics are written to `data/logs/whatch.log`.

The launcher reuses the existing local Python environment and frontend
dependencies. If they have not been prepared yet, it uses `uv` and `npm` to
install them.

### Developer mode

```bash
uv sync --extra test
uv run uvicorn backend.app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The frontend proxies `/api` to FastAPI.

Copy `.env.example` to `.env` and add provider credentials before refreshing
metadata. Whatch uses TMDB for identity/details and OMDb for IMDb, Rotten
Tomatoes, and Metacritic ratings. Credentials are loaded locally and are never
returned by the API.

## Database

The default SQLite database is `data/whatch.db`. Override it with
`WHATCH_DATABASE_URL`. To apply migrations explicitly:

```bash
uv run alembic upgrade head
```

The app also creates missing tables at startup for a frictionless developer
workflow. The Markdown file is always treated as immutable input.

## Metadata policy

- Automatic refresh requires an IMDb ID and resolves it through TMDB's external-ID
  lookup; title search never silently changes a canonical identity.
- Selecting a search result in Needs Review is an explicit user decision.
- Raw provider responses are retained as provenance snapshots.
- Manually edited metadata fields are recorded as overrides and survive refreshes.
- Refresh attempts are durable jobs with success or sanitized failure state.
- Provider calls are title-by-title for now; there is no automatic bulk refresh.
- Controlled backfill runs in resumable batches of at most 25 titles; the Tonight
  screen defaults to five and shows queued/running progress.
- Backfill reuses unexpired provider snapshots, records per-title failures, and
  recovers jobs left running by an interrupted local worker.

## Local recommendations

The Tonight screen ranks only unwatched local titles. Candidate selection is
deterministic: SQL eligibility filters, local semantic-concept similarity,
weighted scoring, feedback-aware preference matching, and an MMR-style
diversity pass that balances genre, story terms, era, language, and production
country instead of treating every metadata token equally. Each result exposes its reasons and score breakdown, and
recommendation sessions are stored for auditability. The local engine does not
call an LLM or an external provider.

Personalization confidence is intentionally low until the catalog contains
enough personal ratings, explicit Tonight feedback, or selected similarity
seeds. Runtime, genre, and description matching improve as metadata coverage
increases. Missing runtime or rating values are soft by default, so partially
enriched titles are not silently discarded; **Require known ratings and
runtime** turns those filters strict.

Original language and production country are optional hard filters in **More
options**. They apply consistently to local, internet, hybrid, and Gemini-assisted
recommendations; provider discovery sends the corresponding codes to TMDB and
validates enriched results again before ranking. The controls suggest common
ISO language/country codes while accepting any valid two- or three-letter code.

The advanced Tonight controls expose tone, pace, and viewing company as soft
context. **More like this**, **Not tonight**, **Another option**, watch-link
opens, selections, impressions, additions, dismissals, and watched outcomes are
recorded locally. Temporary feedback does not permanently dismiss a title;
**Not interested** remains the explicit permanent exclusion.

## Internet discovery

Tonight has three explicit scopes: **My list**, **Internet**, and **Both**.
Internet discovery uses enriched catalog titles as taste seeds, combines TMDB
recommendations with TMDB Discover, then enriches shortlisted candidates with
OMDb ratings. Existing catalog titles and dismissed discoveries are excluded.
Provider candidates are cached locally for seven days; recommendation sessions
and score evidence are stored for auditability.

Online results remain separate until **Add to library** is selected. Each result
includes direct TMDB and IMDb links when available. Hybrid mode runs local and
online recommendation requests concurrently and labels the two result groups.

## Gemini recommendation agent

Whatch can optionally use Google ADK with Gemini as a final shortlist judge.
The deterministic engine still owns retrieval, hard filters, provider lookup,
deduplication, and the candidate set. Gemini may only reorder those validated
candidates and add a concise reason and tradeoff; unknown candidate identifiers
are ignored.

Enable the agent in `.env`:

```dotenv
GEMINI_API_KEY=your_paid_gemini_api_key
WHATCH_GEMINI_ENABLED=true
WHATCH_GEMINI_MODEL=gemini-3.6-flash
```

The **Gemini agent** choice in Tonight is also per-request consent. Whatch sends
the mood and filters plus compact public metadata for the shortlist. Private
notes, the full catalog, watch history, credentials, and provider responses
remain local. If Gemini is disabled, unavailable, times out, or returns invalid
candidate IDs, the endpoint returns the deterministic ranking with an explicit
fallback reason.

ADK runs inside the local FastAPI process for this phase. An A2A service boundary
is deliberately deferred until the recommendation agent needs to run as a
separately deployed or independently owned service; adding that protocol now
would add operational surface without improving this single-user local app.

For Internet and Both scopes, Gemini first creates a bounded provider-search
plan. Whatch executes those queries through TMDB, merges them with taste-seeded
discovery, enriches candidates through OMDb, and then locally enforces catalog
exclusion, dismissals, deduplication, media type, genre, runtime, and rating
constraints. Only the validated shortlist reaches the final Gemini judge. The
Tonight screen exposes the executed search queries as evidence.

Recommendation actions are recorded against the exact session that produced
them, and feedback targets are validated against the stored shortlist.
Aggregate quality signals are available locally at
`GET /api/recommend/evaluation`, including selection, satisfaction, skip,
positive-outcome, and Gemini-fallback rates. No feedback or evaluation data is
sent to Gemini.

## Import policy

- Exact IMDb IDs are merged automatically.
- Every distinct bookmark becomes a source link on the canonical item.
- Imported catalog items start as `want_to_watch`.
- Unmatched rows remain in Needs Review and are never silently discarded.
- Repeating the same import is idempotent.
