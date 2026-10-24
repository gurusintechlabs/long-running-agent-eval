import { lazy, Suspense, type ComponentProps } from "react";
import { Spinner } from "../States";

const Inner = lazy(() => import("./Chart").then((m) => ({ default: m.Chart })));

/** Same props as Chart; ECharts is code-split so non-chart pages stay light. */
export function LazyChart(props: ComponentProps<typeof Inner>) {
  return (
    <Suspense fallback={<div style={{ height: props.height ?? 220 }}><Spinner label="Loading chart" /></div>}>
      <Inner {...props} />
    </Suspense>
  );
}
