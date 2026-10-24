import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./app/Shell";
import { EmptyState } from "./components";
import { CompareView } from "./views/compare";
import { LaunchView } from "./views/launch";
import { LiveView } from "./views/live";
import { ReportsView } from "./views/reports";
import { ReviewView } from "./views/review";
import { RunDetailView } from "./views/run-detail";
import { RunsView } from "./views/runs";
import { SpecEditorPage, SpecsView } from "./views/specs";

// One line per view: each view lives in its own folder under src/views/<name>/ so phases can fill
// them in parallel without touching each other's files.
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/runs" replace />} />
        <Route path="runs" element={<RunsView />} />
        <Route path="runs/:runId" element={<RunDetailView />} />
        <Route path="live" element={<LiveView />} />
        <Route path="live/:runId" element={<LiveView />} />
        <Route path="compare" element={<CompareView />} />
        <Route path="launch" element={<LaunchView />} />
        <Route path="specs" element={<SpecsView />} />
        <Route path="specs/:name" element={<SpecEditorPage />} />
        <Route path="review" element={<ReviewView />} />
        <Route path="review/:runId" element={<ReviewView />} />
        <Route path="reports" element={<ReportsView />} />
        <Route path="*" element={<EmptyState title="Page not found">Use the menu to pick a view.</EmptyState>} />
      </Route>
    </Routes>
  );
}
