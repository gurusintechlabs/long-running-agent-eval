import { useEffect, useState } from "react";

export interface ChartTheme {
  text: string;
  muted: string;
  grid: string;
  surface: string;
  border: string;
  series: string[];
}

function cssVar(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const v = style.getPropertyValue(name).trim();
  return v || fallback;
}

/** Read the design tokens that charts need (canvas cannot use CSS variables directly). */
export function readChartTheme(): ChartTheme {
  const s = getComputedStyle(document.documentElement);
  return {
    text: cssVar(s, "--text", "#1a202c"),
    muted: cssVar(s, "--chart-axis", "#566175"),
    grid: cssVar(s, "--chart-grid", "#e3e7ee"),
    surface: cssVar(s, "--surface", "#ffffff"),
    border: cssVar(s, "--border", "#dde1e7"),
    series: [1, 2, 3, 4, 5, 6, 7].map((i) => cssVar(s, `--series-${i}`, "#2257d4")),
  };
}

/** Re-reads the tokens when the OS colour scheme flips, so charts follow light/dark live. */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(() => readChartTheme());
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setTheme(readChartTheme());
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return theme;
}
