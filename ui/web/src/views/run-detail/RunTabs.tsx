import type { KeyboardEvent } from "react";
import { TABS, type TabId } from "./common/links";

/** WAI-ARIA tabs: roving tabindex, arrow/Home/End keys. The panel is rendered by the parent. */
export function RunTabs({ active, onSelect }: { active: TabId; onSelect: (t: TabId) => void }) {
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let n = -1;
    if (e.key === "ArrowRight") n = (i + 1) % TABS.length;
    else if (e.key === "ArrowLeft") n = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = TABS.length - 1;
    if (n < 0) return;
    e.preventDefault();
    onSelect(TABS[n].id);
    const el = document.getElementById(`tab-${TABS[n].id}`);
    el?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label="Run sections">
      {TABS.map((t, i) => (
        <button
          key={t.id}
          id={`tab-${t.id}`}
          type="button"
          role="tab"
          className={`tab${active === t.id ? " tab-on" : ""}`}
          aria-selected={active === t.id}
          aria-controls="run-tabpanel"
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
