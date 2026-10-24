// Small stroke icons (20x20), one per card kind. Decorative: the text next to them carries the meaning.
const PATHS: Record<string, string> = {
  tool: "M4 6l5 4-5 4M11 15h6",
  result: "M4 10l4 4 8-8",
  error: "M5 5l10 10M15 5L5 15",
  chat: "M3 4h14v9H9l-4 3v-3H3z",
  session: "M10 3a7 7 0 100 14 7 7 0 000-14zM8.5 7l5 3-5 3z",
  flask: "M8 3h4M9 3v5l-4.5 8h11L11 8V3",
  flag: "M5 17V3M5 4h10l-2 3 2 3H5",
  layers: "M10 3l7 4-7 4-7-4zM3 11l7 4 7-4",
  turn: "M4 10h12M12 6l4 4-4 4",
  clock: "M10 3a7 7 0 100 14 7 7 0 000-14zM10 6.5V10l2.5 2",
  play: "M6 4l10 6-10 6z",
  user: "M10 9a3 3 0 100-6 3 3 0 000 6zM4 17c0-3.3 2.7-5 6-5s6 1.7 6 5",
  box: "M3 7l7-4 7 4v6l-7 4-7-4zM3 7l7 4 7-4M10 11v6",
  coin: "M10 3a7 7 0 100 14 7 7 0 000-14zM10 6v8M12 8c0-1.2-4-1.2-4 0s4 .8 4 2-4 1.2-4 0",
  shield: "M10 3l6 2v5c0 4-3 6-6 7-3-1-6-3-6-7V5z",
  stop: "M7 3h6l4 4v6l-4 4H7l-4-4V7zM7.5 7.5l5 5M12.5 7.5l-5 5",
  bars: "M4 16V9M10 16V4M16 16v-5",
  fold: "M3 10h14M7 6l-4 4 4 4M13 6l4 4-4 4",
  braces: "M7 4c-2 0-2 2-2 3s0 2-2 3c2 1 2 2 2 3s0 3 2 3M13 4c2 0 2 2 2 3s0 2 2 3c-2 1-2 2-2 3s0 3-2 3",
  link: "M8 12l4-4M7 9.5l-1.5 1.5a2.5 2.5 0 003.5 3.5L10.5 13M12.5 10.5L14 9a2.5 2.5 0 00-3.5-3.5L9 7",
  copy: "M7 7V4h9v9h-3M4 7h9v9H4z",
  chevron: "M6 8l4 4 4-4",
  search: "M9 15a6 6 0 100-12 6 6 0 000 12zM14 14l3.5 3.5",
  pause: "M7 4v12M13 4v12",
  down: "M10 4v11M5 11l5 5 5-5",
  info: "M10 3a7 7 0 100 14 7 7 0 000-14zM10 9v5M10 6.5v.5",
  check: "M4 10l4 4 8-8",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name] ?? PATHS.braces} />
    </svg>
  );
}
