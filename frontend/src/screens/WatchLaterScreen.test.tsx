// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchWatchLater,
  moveWatchLaterToLibrary,
  removeTitleFromWatchLater,
} from "../api";
import { WatchLaterScreen } from "./WatchLaterScreen";

vi.mock("../api", () => ({
  fetchWatchLater: vi.fn(),
  moveWatchLaterToLibrary: vi.fn(),
  removeTitleFromWatchLater: vi.fn(),
}));

afterEach(cleanup);

describe("WatchLaterScreen", () => {
  it("loads the durable queue, starts similarity search, and removes a title", async () => {
    vi.mocked(fetchWatchLater).mockResolvedValue({
      total: 1,
      items: [{
        id: 42,
        title: "The Conversation",
        media_type: "movie",
        start_year: 1974,
        end_year: null,
        is_ongoing: false,
        imdb_id: "tt0071360",
        imdb_rating: 7.7,
        rotten_tomatoes_rating: 93,
        poster_url: null,
        metadata_status: "enriched",
        status: "want_to_watch",
        priority: "normal",
        user_rating: null,
        link_count: 1,
        tags: [],
        genres: ["Crime", "Drama"],
        watch_later: true,
        added_at: "2026-08-01T12:00:00Z",
      }],
    });
    vi.mocked(removeTitleFromWatchLater).mockResolvedValue(undefined);
    const onCountChange = vi.fn();
    const onFindSimilar = vi.fn();

    render(
      <WatchLaterScreen
        onCountChange={onCountChange}
        onFindSimilar={onFindSimilar}
      />,
    );

    expect(await screen.findByText("The Conversation")).toBeTruthy();
    expect(onCountChange).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: "Find similar tonight" }));
    expect(onFindSimilar).toHaveBeenCalledWith([
      { id: 42, title: "The Conversation", media_type: "movie", year: 1974 },
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(removeTitleFromWatchLater).toHaveBeenCalledWith(42),
    );
    expect(await screen.findByText("Your Watch Later queue is empty.")).toBeTruthy();
    expect(onCountChange).toHaveBeenLastCalledWith(0);
  });

  it("marks a queued title watched and moves it back to the permanent library", async () => {
    vi.mocked(fetchWatchLater).mockResolvedValue({
      total: 1,
      items: [{
        id: 42,
        title: "The Conversation",
        media_type: "movie",
        start_year: 1974,
        end_year: null,
        is_ongoing: false,
        imdb_id: "tt0071360",
        imdb_rating: 7.7,
        rotten_tomatoes_rating: 93,
        poster_url: null,
        metadata_status: "enriched",
        status: "want_to_watch",
        priority: "normal",
        user_rating: null,
        link_count: 1,
        tags: [],
        genres: ["Crime", "Drama"],
        watch_later: true,
        added_at: "2026-08-01T12:00:00Z",
      }],
    });
    vi.mocked(moveWatchLaterToLibrary).mockResolvedValue({
      id: 42,
      title: "The Conversation",
      status: "watched",
      watch_later: false,
    } as never);

    render(
      <WatchLaterScreen onCountChange={vi.fn()} onFindSimilar={vi.fn()} />,
    );
    expect(await screen.findByText("The Conversation")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Watched → Library" }));
    await waitFor(() =>
      expect(moveWatchLaterToLibrary).toHaveBeenCalledWith(42, true),
    );
    expect(await screen.findByText("Your Watch Later queue is empty.")).toBeTruthy();
  });
});
