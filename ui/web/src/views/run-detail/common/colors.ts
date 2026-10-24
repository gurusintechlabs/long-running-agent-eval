import { useMemo } from "react";
import { useChartTheme, type ChartTheme } from "../../../components/chart/theme";

export interface Palette {
  text: string;
  muted: string;
  grid: string;
  surface: string;
  surface2: string;
  border: string;
  accent: string;
  ok: string;
  warn: string;
  bad: string;
  info: string;
  neutral: string;
  series: string[];
}

function v(s: CSSStyleDeclaration, name: string, fb: string): string {
  return s.getPropertyValue(name).trim() || fb;
}

/** Read the semantic colour tokens (canvas cannot use CSS variables). Re-read whenever the chart theme changes. */
export function readPalette(theme: ChartTheme): Palette {
  const s = getComputedStyle(document.documentElement);
  return {
    text: theme.text,
    muted: theme.muted,
    grid: theme.grid,
    surface: theme.surface,
    border: theme.border,
    series: theme.series,
    surface2: v(s, "--surface-2", "#f0f2f5"),
    accent: v(s, "--accent", "#2257d4"),
    ok: v(s, "--ok", "#17703c"),
    warn: v(s, "--warn", "#8a5a00"),
    bad: v(s, "--bad", "#b3261e"),
    info: v(s, "--info", "#1c5fa8"),
    neutral: v(s, "--neutral", "#4a5568"),
  };
}

export function usePalette(): Palette {
  const theme = useChartTheme();
  return useMemo(() => readPalette(theme), [theme]);
}
