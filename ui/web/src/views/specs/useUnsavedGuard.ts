import { useEffect } from "react";

export const LEAVE_MESSAGE = "You have unsaved changes in this spec. Leave this page and lose them?";

/**
 * Warn before losing unsaved work. Covers closing/reloading the tab (beforeunload) and every in-app link click
 * (the app uses BrowserRouter, which has no navigation blocker, so a capturing click listener asks first).
 * Back/forward are not interceptable here; the editor also keeps unsaved edits in sessionStorage and restores them.
 */
export function useUnsavedGuard(dirty: boolean, confirmFn: (msg: string) => boolean = (m) => window.confirm(m)) {
  useEffect(() => {
    if (!dirty) return;
    const onBefore = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]");
      if (!a || a.getAttribute("target") === "_blank" || a.hasAttribute("download")) return;
      const href = a.getAttribute("href") ?? "";
      if (href.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(href)) return; // same-page anchor or external scheme
      if (!confirmFn(LEAVE_MESSAGE)) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", onBefore);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBefore);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty, confirmFn]);
}
