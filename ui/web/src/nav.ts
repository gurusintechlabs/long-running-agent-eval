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
  { to: "/compare", label: "Compare", placeholder: true },
  { to: "/launch", label: "Launch", placeholder: true },
  { to: "/specs", label: "Specs" },
  { to: "/review", label: "Review" },
  { to: "/reports", label: "Reports", placeholder: true },
];
