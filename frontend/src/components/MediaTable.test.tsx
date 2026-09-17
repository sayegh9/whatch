// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MediaTable } from "./MediaTable";
import type { TitleSummary } from "../types";


const KNICK: TitleSummary = {
  id: 165,
  title: "The Knick",
  media_type: "tv",
  start_year: 2014,
  end_year: 2015,
  is_ongoing: false,
  imdb_id: "tt2937900",
  imdb_rating: 8.4,
  rotten_tomatoes_rating: null,
  poster_url: "https://image.tmdb.org/t/p/w500/the-knick.jpg",
  metadata_status: "matched",
  status: "want_to_watch",
  priority: "normal",
  user_rating: null,
  link_count: 3,
  tags: ["medical drama"],
  genres: ["Drama", "History"],
  watch_later: false,
};

afterEach(cleanup);

describe("MediaTable", () => {
  it("renders the poster and opens the selected title", () => {
    const onSelect = vi.fn();
    render(
      <MediaTable
        items={[KNICK]}
        selectedId={null}
        selectedIds={new Set()}
        loading={false}
        sortKey="title"
        sortDirection="asc"
        onSelect={onSelect}
        onToggleSelection={vi.fn()}
        onToggleVisible={vi.fn()}
        onSort={vi.fn()}
      />,
    );

    expect(screen.getByText("The Knick")).toBeTruthy();
    expect(screen.getByText("3 links")).toBeTruthy();
    expect(screen.getByText("2014–2015")).toBeTruthy();
    expect(document.querySelector(".cover-thumbnail")?.getAttribute("src"))
      .toBe(KNICK.poster_url);

    fireEvent.click(screen.getByText("The Knick"));
    expect(onSelect).toHaveBeenCalledWith(165);
  });

  it("sorts only through column header controls and exposes direction", () => {
    const onSort = vi.fn();
    render(
      <MediaTable
        items={[KNICK]}
        selectedId={null}
        selectedIds={new Set()}
        loading={false}
        sortKey="year"
        sortDirection="desc"
        onSelect={vi.fn()}
        onToggleSelection={vi.fn()}
        onToggleVisible={vi.fn()}
        onSort={onSort}
      />,
    );

    const yearButton = screen.getByRole("button", { name: "Year" });
    expect(yearButton.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(yearButton);
    expect(onSort).toHaveBeenCalledWith("year");
  });

  it("selects a title independently from opening its detail row", () => {
    const onSelect = vi.fn();
    const onToggleSelection = vi.fn();
    render(
      <MediaTable
        items={[KNICK]}
        selectedId={null}
        selectedIds={new Set()}
        loading={false}
        sortKey="genre"
        sortDirection="asc"
        onSelect={onSelect}
        onToggleSelection={onToggleSelection}
        onToggleVisible={vi.fn()}
        onSort={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Select The Knick for similar recommendations",
      }),
    );
    expect(onToggleSelection).toHaveBeenCalledWith(KNICK);
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText("Drama · History")).toBeTruthy();
  });
});
