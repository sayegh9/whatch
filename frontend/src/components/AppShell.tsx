import type { ReactNode } from "react";
import {
  DownloadIcon,
  ImportIcon,
  LibraryIcon,
  PlusIcon,
  ReviewIcon,
  TonightIcon,
  WatchLaterIcon,
} from "../icons";
import type { ImportStats, Screen } from "../types";

interface Props {
  active: Screen;
  onNavigate: (screen: Screen) => void;
  importStats: ImportStats | null;
  reviewCount: number;
  watchLaterCount: number;
  onAddTitle: () => void;
  children: ReactNode;
}

const navigation = [
  { id: "library" as const, label: "Library", icon: LibraryIcon },
  { id: "watch_later" as const, label: "Watch later", icon: WatchLaterIcon },
  { id: "tonight" as const, label: "Tonight", icon: TonightIcon },
  { id: "review" as const, label: "Needs review", icon: ReviewIcon },
  { id: "import" as const, label: "Import", icon: ImportIcon },
];

export function AppShell({
  active,
  onNavigate,
  importStats,
  reviewCount,
  watchLaterCount,
  onAddTitle,
  children,
}: Props) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => onNavigate("library")}
          aria-label="Whatch home"
        >
          Whatch
        </button>
        <nav aria-label="Primary navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${active === id ? "is-active" : ""}`}
              onClick={() => onNavigate(id)}
              aria-label={label}
              aria-current={active === id ? "page" : undefined}
            >
              <Icon />
              <span>{label}</span>
              {id === "review" && importStats && reviewCount > 0 ? (
                <span className="nav-count">{reviewCount}</span>
              ) : null}
              {id === "watch_later" && watchLaterCount > 0 ? (
                <span className="nav-count">{watchLaterCount}</span>
              ) : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="local-dot" />
          Local database
        </div>
      </aside>
      <div className="workspace">
        <header className="utility-bar">
          <span className="utility-status">Private · local-first</span>
          <div className="utility-actions">
            <button className="add-title-trigger" type="button" onClick={onAddTitle}>
              <PlusIcon />
              Add title
            </button>
            <a className="export-link" href="/api/export/json" download>
              <DownloadIcon />
              Export JSON
            </a>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
