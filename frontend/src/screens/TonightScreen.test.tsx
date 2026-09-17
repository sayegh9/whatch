// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchMetadataReadiness,
  fetchRecommendationAgentStatus,
  recommendInternet,
  recommendLocal,
  recordRecommendationFeedback,
  updateTitle,
} from "../api";
import { TonightScreen } from "./TonightScreen";

vi.mock("../api", () => ({
  addDiscoveryToWatchLater: vi.fn(),
  addInternetRecommendation: vi.fn(),
  addTitleToWatchLater: vi.fn(),
  dismissInternetRecommendation: vi.fn(),
  dismissRecommendation: vi.fn(),
  fetchMetadataReadiness: vi.fn(),
  fetchRecommendationAgentStatus: vi.fn(),
  recommendAgent: vi.fn(),
  recommendInternet: vi.fn(),
  recommendLocal: vi.fn(),
  recordRecommendationFeedback: vi.fn(),
  retryMetadataJobs: vi.fn(),
  removeTitleFromWatchLater: vi.fn(),
  startMetadataBackfill: vi.fn(),
  updateTitle: vi.fn(),
}));

const mockedRecommendLocal = vi.mocked(recommendLocal);
const mockedRecommendInternet = vi.mocked(recommendInternet);
const mockedFetchMetadataReadiness = vi.mocked(fetchMetadataReadiness);
const mockedFetchRecommendationAgentStatus = vi.mocked(
  fetchRecommendationAgentStatus,
);
const mockedRecordRecommendationFeedback = vi.mocked(recordRecommendationFeedback);
const mockedUpdateTitle = vi.mocked(updateTitle);

afterEach(cleanup);

function localResponse(limit: number) {
  return {
    session_id: limit,
    mode: "local" as const,
    confidence: "medium" as const,
    confidence_reason: "Enough matching catalog titles.",
    candidate_count: 20,
    metadata_coverage: {
      total: 20,
      runtime: 20,
      genres: 20,
      overview: 20,
    },
    criteria: {},
    results: Array.from({ length: limit }, (_, index) => ({
      title_id: index + 1,
      title: `Local ${index + 1}`,
      media_type: "movie" as const,
      year: 2000 + index,
      runtime_minutes: 100,
      genres: ["Drama"],
      original_language: "en",
      production_countries: ["US"],
      poster_url: null,
      imdb_id: `tt${index + 1}`,
      imdb_rating: 7,
      rotten_tomatoes_rating: 80,
      status: "want_to_watch",
      priority: "normal",
      watch_later: false,
      score: 0.8,
      score_breakdown: { criteria_match: 0.2 },
      reasons: ["Matches tonight"],
      agent_reason: null,
      agent_tradeoff: null,
      links: [],
    })),
  };
}

function internetResponse(limit: number) {
  return {
    session_id: limit + 100,
    mode: "internet" as const,
    confidence: "medium" as const,
    candidate_count: 20,
    criteria: {},
    search_queries: [],
    results: Array.from({ length: limit }, (_, index) => ({
      candidate_id: index + 100,
      tmdb_id: index + 200,
      media_type: "movie" as const,
      imdb_id: `tt-online-${index + 1}`,
      title: `Internet ${index + 1}`,
      year: 2010 + index,
      runtime_minutes: 105,
      genres: ["Thriller"],
      original_language: "en",
      production_countries: ["US"],
      overview: "An online discovery.",
      poster_url: null,
      imdb_rating: 7.2,
      rotten_tomatoes_rating: 82,
      tmdb_vote_average: 7.3,
      score: 0.79,
      score_breakdown: { criteria_match: 0.2 },
      reasons: ["Matches tonight"],
      agent_reason: null,
      agent_tradeoff: null,
      seed_titles: [],
      tmdb_url: `https://www.themoviedb.org/movie/${index + 200}`,
    })),
  };
}

describe("TonightScreen load more", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mockedFetchMetadataReadiness.mockResolvedValue({
      total: 20,
      eligible: 20,
      enriched: 20,
      runtime: 20,
      genres: 20,
      overview: 20,
      queued: 0,
      running: 0,
      failed: 0,
    });
    mockedFetchRecommendationAgentStatus.mockResolvedValue({
      available: true,
      enabled: true,
      configured: true,
      model: "gemini-test",
      privacy_summary: "Test status",
    });
    mockedRecommendLocal.mockImplementation(async ({ limit }) => localResponse(limit));
    mockedRecommendInternet.mockImplementation(async ({ limit }) =>
      internetResponse(limit),
    );
    mockedRecordRecommendationFeedback.mockResolvedValue({ id: 1, recorded: true });
    mockedUpdateTitle.mockResolvedValue(undefined as never);
  });

  it("renders every returned result and supports repeated hybrid loads", async () => {
    render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Find something to watch" }),
    );

    expect(await screen.findByText("Local 5")).toBeTruthy();
    expect(screen.getByText("Internet 5")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Load 5 more from each source" }),
    );

    expect(await screen.findByText("Local 10")).toBeTruthy();
    expect(screen.getByText("Internet 10")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Load 5 more from each source" }),
    );

    expect(await screen.findByText("Local 15")).toBeTruthy();
    expect(screen.getByText("Internet 15")).toBeTruthy();
    await waitFor(() => {
      expect(mockedRecommendLocal).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 15 }),
      );
      expect(mockedRecommendInternet).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 15 }),
      );
    });
  });

  it("keeps a clear disabled progress control when every matching option is loaded", async () => {
    mockedRecommendLocal.mockImplementation(async ({ limit }) => ({
      ...localResponse(Math.min(limit, 5)),
      candidate_count: 5,
    }));
    render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Recommendation sources"), {
      target: { value: "local" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Find something to watch" }),
    );

    const complete = await screen.findByRole("button", {
      name: "All matching options loaded",
    });
    expect(complete).toHaveProperty("disabled", true);
    expect(screen.getByText(/5 loaded · complete/)).toBeTruthy();
  });

  it("sends explicit Tonight context and records temporary feedback", async () => {
    render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "More options" }));
    fireEvent.click(screen.getByRole("button", { name: "light" }));
    fireEvent.click(screen.getByRole("button", { name: "fast" }));
    fireEvent.click(screen.getByRole("button", { name: "group" }));
    fireEvent.change(screen.getByLabelText("Release year direction"), {
      target: { value: "before" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Release year" }), {
      target: { value: "1995" },
    });
    fireEvent.change(screen.getByLabelText("Original language"), {
      target: { value: "ar" },
    });
    fireEvent.change(screen.getByLabelText("Production country"), {
      target: { value: "EG" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /Require known ratings and runtime/,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Find something to watch" }),
    );

    expect(await screen.findByText("Local 1")).toBeTruthy();
    expect(mockedRecommendLocal).toHaveBeenCalledWith(
      expect.objectContaining({
        tone: "light",
        pace: "fast",
        company: "group",
        strict_metadata: true,
        release_year_mode: "before",
        release_year: 1995,
        language: "ar",
        production_country: "EG",
      }),
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Not tonight" })[0]);
    await waitFor(() => {
      expect(mockedRecordRecommendationFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          source: "local",
          action: "not_tonight",
          media_item_id: 1,
        }),
      );
    });
    expect(screen.queryByText("Local 1")).toBeNull();
  });

  it("shows the release year beside each similarity seed", () => {
    render(
      <TonightScreen
        seedTitles={[{ id: 44, title: "Seed Film", media_type: "movie", year: 1990 }]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "More options" }));
    expect(screen.getByText("Seed Film (1990)")).toBeTruthy();
  });

  it("captures satisfaction after a recommended title is watched", async () => {
    render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Find something to watch" }),
    );

    const title = await screen.findByText("Local 1");
    const card = title.closest("article");
    expect(card).not.toBeNull();
    fireEvent.click(within(card!).getByRole("button", { name: "Mark watched" }));

    expect(
      await within(card!).findByText("Did this recommendation work for you?"),
    ).toBeTruthy();
    fireEvent.click(within(card!).getByRole("button", { name: "Liked it" }));

    await waitFor(() => {
      expect(mockedRecordRecommendationFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          source: "local",
          action: "liked",
          media_item_id: 1,
        }),
      );
    });
  });

  it("restores the shortlist for this browser session and clears it when criteria change", async () => {
    const firstRender = render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Find something to watch" }),
    );
    expect(await screen.findByText("Local 5")).toBeTruthy();
    expect(mockedRecommendLocal).toHaveBeenCalledTimes(1);
    expect(mockedRecommendInternet).toHaveBeenCalledTimes(1);

    firstRender.unmount();
    render(
      <TonightScreen
        seedTitles={[]}
        onClearSeeds={vi.fn()}
        onWatchLaterChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Local 5")).toBeTruthy();
    expect(screen.getByText("Internet 5")).toBeTruthy();
    expect(mockedRecommendLocal).toHaveBeenCalledTimes(1);
    expect(mockedRecommendInternet).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Media type"), {
      target: { value: "tv" },
    });
    await waitFor(() => expect(screen.queryByText("Local 5")).toBeNull());
    expect(screen.getByText("Your shortlist will appear here.")).toBeTruthy();
  });
});
