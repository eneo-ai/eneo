import { init, registerTheme, type EChartsCoreOption, use } from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  TooltipComponent,
  GridComponent,
  DatasetComponent,
  TransformComponent
} from "echarts/components";
import { UniversalTransition } from "echarts/features";
import { CanvasRenderer } from "echarts/renderers";

import type { Action } from "svelte/action";
import { eneoTheme } from "./theme.js";

use([
  BarChart,
  TooltipComponent,
  GridComponent,
  DatasetComponent,
  TransformComponent,
  UniversalTransition,
  CanvasRenderer
]);

export type Config = {
  options: EChartsCoreOption;
  theme?: string | object;
};

registerTheme("eneo", eneoTheme);

export const chart: Action<HTMLElement, Config> = (node, params) => {
  const { theme = "eneo" } = params;
  const options: EChartsCoreOption = {
    aria: {
      enabled: true
    },
    tooltip: {
      show: true
    },
    grid: {
      left: 0,
      top: 5,
      right: 5,
      bottom: 0,
      containLabel: true
    },
    ...params.options
  };

  const chart = init(node, theme, { renderer: "canvas" });
  chart.setOption(options);

  const resizeObserver = new ResizeObserver(() => chart.resize());
  resizeObserver.observe(node);

  return {
    destroy() {
      chart.dispose();
      resizeObserver.disconnect();
    },

    update(newParams: Config) {
      chart.setOption({
        ...params.options,
        ...newParams.options
      });
    }
  };
};
