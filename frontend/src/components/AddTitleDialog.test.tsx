// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { commitTitleIntake, resolveTitleIntake } from "../api";
import { AddTitleDialog } from "./AddTitleDialog";


vi.mock("../api", () => ({
  commitTitleIntake: vi.fn(),
  resolveTitleIntake: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AddTitleDialog", () => {
  it("resolves a title, confirms the destination, and commits the selected match", async () => {
    vi.mocked(resolveTitleIntake).mockResolvedValue({
      input_kind: "title",
      exact: false,
      normalized_input: "Perfect Days",
      source_url: null,
      candidates: [{
        tmdb_id: 976893,
        media_type: "movie",
        title: "Perfect Days",
        original_title: "PERFECT DAYS",
        release_date: "2023-11-10",
        overview: "A Tokyo cleaner finds beauty in ordinary life.",
        poster_url: "https://image.tmdb.org/t/p/w342/perfect.jpg",
        tmdb_vote_average: 7.8,
        existing_media_item_id: null,
      }],
    });
    vi.mocked(commitTitleIntake).mockResolvedValue({
      item: { id: 77, title: "Perfect Days", watch_later: true } as never,
      created: true,
      destination: "watch_later",
    });
    const onAdded = vi.fn();

    render(<AddTitleDialog onClose={vi.fn()} onAdded={onAdded} />);
    fireEvent.change(screen.getByLabelText("Movie name or link"), {
      target: { value: "Perfect Days" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Watch Later/ }));
    fireEvent.click(screen.getByRole("button", { name: "Find title" }));

    expect(await screen.findByText("Perfect Days")).toBeTruthy();
    expect(screen.getByText("2023", { exact: false })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add to Watch Later" }));

    await waitFor(() => {
      expect(commitTitleIntake).toHaveBeenCalledWith({
        tmdb_id: 976893,
        media_type: "movie",
        destination: "watch_later",
        source_url: undefined,
      });
    });
    expect(onAdded).toHaveBeenCalledWith(
      [expect.objectContaining({ id: 77, title: "Perfect Days" })],
      "watch_later",
    );
  });

  it("shows suggestions after the user pauses typing", async () => {
    vi.mocked(resolveTitleIntake).mockResolvedValue({
      input_kind: "title",
      exact: false,
      normalized_input: "Perfect Days",
      source_url: null,
      candidates: [{
        tmdb_id: 976893,
        media_type: "movie",
        title: "Perfect Days",
        original_title: null,
        release_date: "2023-11-10",
        overview: null,
        poster_url: null,
        tmdb_vote_average: 7.8,
        existing_media_item_id: null,
      }],
    });

    render(<AddTitleDialog onClose={vi.fn()} onAdded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Movie name or link"), {
      target: { value: "Perfect Days" },
    });

    await waitFor(() => expect(resolveTitleIntake).toHaveBeenCalledWith({
      input: "Perfect Days",
      media_type: "either",
    }), { timeout: 1200 });
    expect(await screen.findByText("Perfect Days")).toBeTruthy();
  });

  it("previews and commits multiple reviewed matches", async () => {
    vi.mocked(resolveTitleIntake)
      .mockResolvedValueOnce({
        input_kind: "title", exact: false, normalized_input: "Perfect Days", source_url: null,
        candidates: [{ tmdb_id: 1, media_type: "movie", title: "Perfect Days", original_title: null, release_date: "2023-01-01", overview: null, poster_url: null, tmdb_vote_average: 8, existing_media_item_id: null }],
      })
      .mockResolvedValueOnce({
        input_kind: "title", exact: false, normalized_input: "Severance", source_url: null,
        candidates: [{ tmdb_id: 2, media_type: "tv", title: "Severance", original_title: null, release_date: "2022-01-01", overview: null, poster_url: null, tmdb_vote_average: 8.5, existing_media_item_id: null }],
      });
    vi.mocked(commitTitleIntake)
      .mockResolvedValueOnce({ item: { id: 1, title: "Perfect Days" } as never, created: true, destination: "library" })
      .mockResolvedValueOnce({ item: { id: 2, title: "Severance" } as never, created: true, destination: "library" });
    const onAdded = vi.fn();

    render(<AddTitleDialog onClose={vi.fn()} onAdded={onAdded} />);
    fireEvent.click(screen.getByRole("button", { name: "Bulk add" }));
    fireEvent.change(screen.getByLabelText("Titles to add"), {
      target: { value: "Perfect Days\nSeverance" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review matches" }));

    expect(await screen.findByRole("button", { name: "Add 2 to Library" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add 2 to Library" }));
    await waitFor(() => expect(onAdded).toHaveBeenCalledWith([
      expect.objectContaining({ id: 1 }),
      expect.objectContaining({ id: 2 }),
    ], "library"));
  });
});
