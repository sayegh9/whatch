import { useCallback, useEffect, useState } from "react";
import { fetchReview, fetchWatchLater, latestImport } from "./api";
import { AppShell } from "./components/AppShell";
import { AddTitleDialog } from "./components/AddTitleDialog";
import { ImportScreen } from "./screens/ImportScreen";
import { LibraryScreen } from "./screens/LibraryScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { TonightScreen } from "./screens/TonightScreen";
import { WatchLaterScreen } from "./screens/WatchLaterScreen";
import type { ImportStats, RecommendationSeed, Screen } from "./types";

export default function App() {
  const [screen, setScreen] = useState<Screen>("library");
  const [importStats, setImportStats] = useState<ImportStats | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [watchLaterCount, setWatchLaterCount] = useState(0);
  const [recommendationSeeds, setRecommendationSeeds] = useState<RecommendationSeed[]>([]);
  const [addTitleOpen, setAddTitleOpen] = useState(false);
  const [libraryVersion, setLibraryVersion] = useState(0);

  const refreshWatchLaterCount = useCallback(async () => {
    try {
      const response = await fetchWatchLater();
      setWatchLaterCount(response.total);
    } catch {
      setWatchLaterCount(0);
    }
  }, []);

  const findSimilar = useCallback((seeds: RecommendationSeed[]) => {
    setRecommendationSeeds(seeds);
    setScreen("tonight");
  }, []);

  useEffect(() => {
    latestImport().then(setImportStats).catch(() => setImportStats(null));
    fetchReview().then((rows) => setReviewCount(rows.length)).catch(() => setReviewCount(0));
    void refreshWatchLaterCount();
  }, [refreshWatchLaterCount]);

  return (
    <AppShell
      active={screen}
      onNavigate={setScreen}
      importStats={importStats}
      reviewCount={reviewCount}
      watchLaterCount={watchLaterCount}
      onAddTitle={() => setAddTitleOpen(true)}
    >
      {screen === "library" ? (
        <LibraryScreen
          key={libraryVersion}
          importStats={importStats}
          onImport={() => setScreen("import")}
          onFindSimilar={findSimilar}
          onWatchLaterChange={refreshWatchLaterCount}
        />
      ) : null}
      {screen === "watch_later" ? (
        <WatchLaterScreen
          onCountChange={setWatchLaterCount}
          onFindSimilar={findSimilar}
        />
      ) : null}
      {screen === "review" ? <ReviewScreen onCountChange={setReviewCount} /> : null}
      {screen === "tonight" ? (
        <TonightScreen
          seedTitles={recommendationSeeds}
          onClearSeeds={() => setRecommendationSeeds([])}
          onWatchLaterChange={refreshWatchLaterCount}
        />
      ) : null}
      {screen === "import" ? (
        <ImportScreen
          current={importStats}
          onChange={setImportStats}
          onComplete={() => setScreen("library")}
        />
      ) : null}
      {addTitleOpen ? (
        <AddTitleDialog
          onClose={() => setAddTitleOpen(false)}
          onAdded={(_items, destination) => {
            setAddTitleOpen(false);
            setLibraryVersion((current) => current + 1);
            void refreshWatchLaterCount();
            setScreen(destination === "watch_later" ? "watch_later" : "library");
          }}
        />
      ) : null}
    </AppShell>
  );
}
