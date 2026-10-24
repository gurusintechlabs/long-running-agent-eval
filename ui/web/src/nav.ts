export interface NavItem {
  to: string;
  label: string;
  /** Not built yet: shown with a "soon" tag. Flip to false when a phase fills the view in. */
  placeholder?: boolean;
}

// Run detail (/runs/:runId) is reached from the Runs table, so it has no entry of its own.
export const NAV: NavItem[] = [
  { to: "/runs", label: "Runs" },
  { to: "/live", label: "Live", placeholder: true },
  { to: "/compare", label: "Compare" },
  { to: "/launch", label: "Launch" },
  { to: "/specs", label: "Specs", placeholder: true },
  { to: "/review", label: "Review", placeholder: true },
  { to: "/reports", label: "Reports" },
];
