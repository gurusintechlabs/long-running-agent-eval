// Tree-shaken ECharts: only the pieces the UI uses. Other views register more here when they need them
// (heatmap, scatter, custom series...), which keeps the base bundle small.
import { LineChart } from "echarts/charts";
import { DataZoomInsideComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomInsideComponent, CanvasRenderer]);

export { echarts };
export type { EChartsCoreOption as ChartOption, ECharts } from "echarts/core";
