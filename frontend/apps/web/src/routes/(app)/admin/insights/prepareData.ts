/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { AnalyticsAggregatedData } from "@intric/intric-js";
import type { Chart } from "@intric/ui";
import { fromAbsolute, getDayOfWeek, parseAbsolute, toCalendarDate } from "@internationalized/date";
import { m } from "$lib/paraglide/messages";

// {sessions: { "Monday": {count: 12, total: 12}}}
type UsageData = Record<string, Record<string, { count: number; total: number }>>;

// Optimized count: avoids repeated hasOwn checks by using nullish coalescing assignment
const count = (
  typeData: Record<string, { count: number; total: number }>,
  key: string | number,
  increment = 1
): void => {
  const k = String(key);
  const entry = typeData[k];
  if (entry) {
    entry.count += increment;
  } else {
    typeData[k] = { count: increment, total: 0 };
  }
};

// Optimized total: direct property access, no Object.entries allocation
const computeTotals = (obj: UsageData): void => {
  const keys = Object.keys(obj);
  for (let i = 0; i < keys.length; i++) {
    const resource = keys[i];
    const row = obj[resource];
    const dateKeys = Object.keys(row).sort();
    let runningTotal = 0;
    for (let j = 0; j < dateKeys.length; j++) {
      const entry = row[dateKeys[j]];
      runningTotal += entry.count;
      entry.total = runningTotal;
    }
  }
};

// Optimized flatten: pre-allocate array, avoid intermediate allocations
const flatten = (obj: UsageData) => {
  const types = Object.keys(obj);
  // Count total entries first
  let totalEntries = 0;
  for (let i = 0; i < types.length; i++) {
    totalEntries += Object.keys(obj[types[i]]).length;
  }

  const rows: Array<{ created_at: string; type: string; count: number; total: number }> =
    new Array(totalEntries);
  let idx = 0;

  for (let i = 0; i < types.length; i++) {
    const type = types[i];
    const typeData = obj[type];
    const dateKeys = Object.keys(typeData);
    for (let j = 0; j < dateKeys.length; j++) {
      const created_at = dateKeys[j];
      const data = typeData[created_at];
      rows[idx++] = { created_at, type, count: data.count, total: data.total };
    }
  }

  // Sort by created_at: use numeric comparison for hours/weekdays, string for dates
  rows.sort((a, b) => {
    const aVal = a.created_at;
    const bVal = b.created_at;
    // If both are numeric (hours 0-23 or weekdays 0-6), compare as numbers
    const aNum = Number(aVal);
    const bNum = Number(bVal);
    if (!isNaN(aNum) && !isNaN(bNum)) {
      return aNum - bNum;
    }
    // Otherwise compare as strings (dates in YYYY-MM-DD format)
    return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
  });
  return rows;
};

// Optimized getMaxCount: single pass, no intermediate array
const getMaxCount = (obj: UsageData): number => {
  const questions = obj.questions;
  if (!questions) return 5;

  let maxCount = 0;
  const keys = Object.keys(questions);
  for (let i = 0; i < keys.length; i++) {
    const c = questions[keys[i]].count;
    if (c > maxCount) maxCount = c;
  }
  return Math.ceil(maxCount / 5) * 5 || 5;
};

// Lazy-initialized days array
let _days: string[] | null = null;
const getDays = (): string[] => {
  if (!_days) {
    _days = [
      m.monday(),
      m.tuesday(),
      m.wednesday(),
      m.thursday(),
      m.friday(),
      m.saturday(),
      m.sunday()
    ];
  }
  return _days;
};

type PreparedData = Chart.Config["options"] & { dataset: Record<string, unknown>[] };

// Optimized: Find earliest and latest dates in single pass without array allocations
const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;
function getDataDateBounds(usageByDate: UsageData): { earliest: string | null; latest: string | null } {
  let earliest: string | null = null;
  let latest: string | null = null;

  const sources = [usageByDate.sessions, usageByDate.questions];
  for (let i = 0; i < sources.length; i++) {
    const source = sources[i];
    if (!source) continue;
    const keys = Object.keys(source);
    for (let j = 0; j < keys.length; j++) {
      const d = keys[j];
      if (!DATE_REGEX.test(d)) continue;
      if (earliest === null || d < earliest) earliest = d;
      if (latest === null || d > latest) latest = d;
    }
  }

  return { earliest, latest };
}

export function prepareData(
  data: AnalyticsAggregatedData,
  timeframe: { start: string; end: string }
) {
  const usageByDate: UsageData = { sessions: {}, assistants: {}, questions: {} };
  const usageByWeekday: UsageData = { sessions: {}, assistants: {}, questions: {} };
  const usageByHour: UsageData = { sessions: {}, assistants: {}, questions: {} };

  // Process each resource type with optimized loop
  const resourceTypes = ["sessions", "assistants", "questions"] as const;
  for (let r = 0; r < resourceTypes.length; r++) {
    const resource = resourceTypes[r];
    const rows = data[resource];
    if (!rows) continue;

    const dateData = usageByDate[resource];
    const weekdayData = usageByWeekday[resource];
    const hourData = usageByHour[resource];

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      if (!row.created_at) continue;

      const increment = typeof row.count === "number" ? row.count : 1;

      // Parse once, extract all values
      const timestamp = parseAbsolute(row.created_at, "Europe/Stockholm");
      const date = toCalendarDate(timestamp).toString();
      const day = getDayOfWeek(timestamp, "sv-SE");
      const hours = timestamp.hour;

      // Direct reference to type-specific objects avoids repeated property lookups
      count(dateData, date, increment);
      count(weekdayData, day, increment);
      count(hourData, hours, increment);
    }
  }

  computeTotals(usageByDate);

  // Calculate actual data bounds
  const dataBounds = getDataDateBounds(usageByDate);

  // Extract date-only from timeframe (strip time component)
  const requestedStartDate = timeframe.start.split("T")[0];

  // Determine effective x-axis start: use actual data start if later than requested
  const effectiveStartDate = dataBounds.earliest && dataBounds.earliest > requestedStartDate
    ? dataBounds.earliest
    : requestedStartDate;

  const byDate: PreparedData = {
    xAxis: {
      animation: false,
      type: "time",
      // Use effective start (bounded by actual data) instead of requested timeframe
      min: parseAbsolute(`${effectiveStartDate}T00:00:00+01:00`, "Europe/Stockholm").subtract({ days: 1 }).toDate(),
      max: timeframe.end,
      axisLabel: {
        // Shorter date format: MM-DD instead of YYYY-MM-DD
        formatter: (value: number) => {
          const date = toCalendarDate(fromAbsolute(value, "Europe/Stockholm"));
          const month = date.month.toString().padStart(2, "0");
          const day = date.day.toString().padStart(2, "0");
          return `${month}-${day}`;
        }
      }
    },
    yAxis: {
      type: "value",
      min: 0,
      max: getMaxCount(usageByDate)
    },
    dataset: [
      {
        dimensions: ["created_at", "type", "count", "total"],
        source: flatten(usageByDate)
      }
    ]
  };

  const byWeekday: PreparedData = {
    xAxis: {
      animation: false,
      type: "category",
      data: [0, 1, 2, 3, 4, 5, 6], // Pre-allocated array instead of Array.from
      axisLabel: {
        // @ts-expect-error ignore any type
        formatter: (value) => {
          const days = getDays();
          const idx = typeof value === "string" ? parseInt(value, 10) : value;
          return days[idx] ?? "?";
        }
      }
    },
    yAxis: { type: "value", min: 0, max: getMaxCount(usageByWeekday) },
    dataset: [
      {
        dimensions: ["created_at", "type", "count", "total"],
        source: flatten(usageByWeekday)
      }
    ]
  };

  const byHour: PreparedData = {
    xAxis: {
      animation: false,
      type: "category",
      // Pre-allocated static array
      data: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
      axisLabel: {
        formatter: (value: string) => `${value}:00`
      }
    },
    yAxis: { type: "value", min: 0, max: getMaxCount(usageByHour) },
    dataset: [
      {
        dimensions: ["created_at", "type", "count", "total"],
        source: flatten(usageByHour)
      }
    ]
  };

  return { byDate, byWeekday, byHour };
}

export function getConfig(data: PreparedData, filter: "sessions" | "questions"): Chart.Config {
  const label = filter === "sessions" ? m.conversations() : filter;

  return {
    options: {
      grid: {
        left: 48,
        right: 24,
        top: 24,
        bottom: 48,
        containLabel: true
      },
      xAxis: {
        ...data.xAxis,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          ...data.xAxis?.axisLabel,
          // Use actual color value - ECharts canvas doesn't support CSS variables
          // #9CA3AF (gray-400) is visible on both light and dark backgrounds
          color: "#9CA3AF",
          fontSize: 10,
          margin: 16,
          hideOverlap: true
        }
      },
      yAxis: {
        ...data.yAxis,
        axisLine: {
          show: true,
          lineStyle: {
            color: "rgba(156, 163, 175, 0.4)", // gray-400 with opacity
            width: 1
          }
        },
        axisTick: { show: false },
        axisLabel: {
          // Use actual color value for canvas rendering
          color: "#9CA3AF",
          fontSize: 10,
          margin: 8
        },
        splitLine: {
          lineStyle: {
            color: "rgba(156, 163, 175, 0.2)", // gray-400 with low opacity
            type: "dashed"
          }
        }
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(30, 30, 30, 0.95)", // Dark background for tooltip
        borderColor: "rgba(156, 163, 175, 0.3)",
        borderWidth: 1,
        borderRadius: 8,
        padding: [12, 16],
        textStyle: {
          color: "#F3F4F6", // gray-100 for readability
          fontSize: 13
        },
        extraCssText: "box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25); backdrop-filter: blur(8px);",
        // @ts-expect-error formatter typing
        formatter: (params: { name: string; value: number; data: { count?: number } }[]) => {
          const item = Array.isArray(params) ? params[0] : params;
          const value = item.data?.count ?? item.value;
          return `<div style="font-size: 11px; color: #9CA3AF; margin-bottom: 4px;">${item.name}</div><div style="font-size: 18px; font-weight: 600; color: #F3F4F6;">${value}</div>`;
        },
        axisPointer: {
          type: "shadow",
          shadowStyle: {
            color: "rgba(14, 165, 233, 0.06)"
          },
          label: {
            // @ts-expect-errorignore any type
            formatter: (params) => {
              // @ts-expect-error axisLabel is not properly typed?
              return data.xAxis?.axisLabel?.formatter(params.value) ?? params.value.toString();
            }
          }
        }
      },
      dataset: [
        ...data.dataset,
        {
          id: "filtered",
          transform: {
            type: "filter",
            config: { dimension: "type", value: filter }
          }
        }
      ],
      series: [
        {
          type: "bar",
          dimensions: ["created_at", "count"],
          name: `${m.new()} ${label}`,
          datasetId: "filtered",
          barMaxWidth: 40,
          barCategoryGap: "20%",
          barGap: "10%",
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            shadowColor: "rgba(59, 130, 246, 0.15)",
            shadowBlur: 4,
            shadowOffsetY: 1,
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "#60A5FA" },  // blue-400
                { offset: 1, color: "#2563EB" }   // blue-600
              ]
            }
          },
          emphasis: {
            itemStyle: {
              // Shadow-only hover for Nordic minimalism - no color change
              shadowBlur: 12,
              shadowColor: "rgba(59, 130, 246, 0.3)",
              shadowOffsetY: 3
            }
          },
          animationDuration: 400,
          animationEasing: "cubicOut",
          animationDurationUpdate: 200,
          animationEasingUpdate: "cubicOut",
          animationDelay: (idx: number) => idx * 30
        }
      ]
    }
  };
}
