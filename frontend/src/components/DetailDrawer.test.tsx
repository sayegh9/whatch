// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TitleDetail } from "../types";
import { DetailDrawer } from "./DetailDrawer";


const DETAIL: TitleDetail = {
  id: 1,
  title: "Perfect Days",
  original_title: "PERFECT DAYS",
  media_type: "movie",
  start_year: 2023,
  end_year: null,
  is_ongoing: false,
  imdb_id: "tt27503384",
  imdb_rating: 7.9,
  rotten_tomatoes_rating: 96,
  poster_url: "https://image.tmdb.org/perfect.jpg",
  metadata_status: "enriched",
  status: "want_to_watch",
  priority: "normal",
  user_rating: null,
  link_count: 1,
  tags: [],
  genres: ["Drama"],
  watch_later: false,
  runtime_minutes: 124,
  release_date: "2023-11-10",
  original_language: "ja",
  overview: "A Tokyo cleaner finds beauty in ordinary life.",
  metacritic_rating: 80,
  tmdb_vote_average: 7.8,
  tmdb_vote_count: 1500,
  metadata_refreshed_at: "2026-08-08T00:00:00Z",
  manual_fields: [],
  notes: null,
  links: [],
};

afterEach(cleanup);

describe("DetailDrawer metadata corrections", () => {
  it("sends only changed metadata fields so provider-managed values remain refreshable", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <DetailDrawer
        detail={DETAIL}
        loading={false}
        onClose={vi.fn()}
        onSave={onSave}
        onRefresh={vi.fn()}
        onToggleWatchLater={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Correct metadata" }));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Perfect Days (2023)" } });
    fireEvent.change(screen.getByLabelText("IMDb rating"), { target: { value: "8.0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      title: "Perfect Days (2023)",
      imdb_rating: 8,
    })));
    const payload = onSave.mock.calls[0][0];
    expect(payload).not.toHaveProperty("runtime_minutes");
    expect(payload).not.toHaveProperty("genres");
  });
});
