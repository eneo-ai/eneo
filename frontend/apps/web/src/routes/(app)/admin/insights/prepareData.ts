/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import type { AnalyticsData } from "@intric/intric-js";
import type { Chart } from "@intric/ui";
import { fromAbsolute, getDayOfWeek, parseAbsolute, toCalendarDate } from "@internationalized/date";
import { m } from "$lib/paraglide/messages";

// {sessions: { "Monday": {count: 12, total: 12}}}
type UsageData = Record<string, Record<string, Record<string, number>>>;

type CountFn = <T extends keyof UsageData>(
  obj: UsageData,
  type: T,
  field: string,
  date: string | number
) => void;

const count: CountFn = (obj, type, field, date) => {
  if (Object.hasOwn(obj[type], date)) {
    obj[type][date][field] += 1;
  } else {
    obj[type][date] = {};
    obj[type][date][field] = 1;
  }
};

const total = (objs: UsageData[]) => {
  for (const obj of objs) {
    for (const [resource, row] of Object.entries(obj)) {
      let total = 0;
      for (const [date, data] of Object.entries(row)) {
        total += data.count;
        obj[resource][date].total = total;
      }
    }
  }
};

const flatten = (obj: UsageData) => {
  const rows = Object.entries(obj)
    .flatMap(([type, rows]) => {
      return Object.entries(rows).map(([created_at, data]) => {
        return { created_at, type, ...data };
      });
    })
    .toSorted(
      (a, b) =>
        parseInt(a.created_at.replaceAll("-", "")) - parseInt(b.created_at.replaceAll("-", ""))
    );
  return rows;
};

const getMaxCount = (obj: UsageData) => {
  const counts = Object.values(obj.questions).map((item) => item.count);
  return Math.ceil(Math.max(...counts) / 5) * 5;
};

const days = [m.monday(), m.tuesday(), m.wednesday(), m.thursday(), m.friday(), m.saturday(), m.sunday()];

type PreparedData = Chart.Config["options"] & { dataset: Record<string, unknown>[] };

export function prepareData(data: AnalyticsData, timeframe: { start: string; end: string }) {
  const usageByDate: UsageData = { sessions: {}, assistants: {}, questions: {} };
  const usageByWeekday: UsageData = { sessions: {}, assistants: {}, questions: {} };
  const usageByHour: UsageData = { sessions: {}, assistants: {}, questions: {} };

  for (const [resource, rows] of Object.entries(data)) {
    rows.forEach((row) => {
      if (!row.created_at) return;
      const timestamp = parseAbsolute(row.created_at, "Europe/Stockholm");
      const date = toCalendarDate(timestamp).toString();
      const day = getDayOfWeek(timestamp, "sv-SE");
      const hours = timestamp.hour;

      count(usageByDate, resource, "count", date);
      count(usageByWeekday, resource, "count", day);
      count(usageByHour, resource, "count", hours);
    });
  }

  total([usageByDate]);

  const byDate: PreparedData = {
    xAxis: {
      animation: false,
      type: "time",
      min: parseAbsolute(timeframe.start, "Europe/Stockholm").subtract({ days: 1 }).toDate(),
      max: timeframe.end,
      axisLabel: {
        formatter: (value: number) => {
          return toCalendarDate(fromAbsolute(value, "Europe/Stockholm")).toString();
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
      data: Array.from(new Array(7), (x, i) => i),
      axisLabel: {
        // @ts-expect-error ignore any type
        formatter: (value) => {
          if (typeof value === "string" && Object.hasOwn(days, value)) {
            // @ts-expect-error type doesnt narrow properly
            return days[value];
          }
          return "?";
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
      data: Array.from(new Array(24), (x, i) => i),
      axisLabel: {
        formatter: (value: string) => {
          return `${value}:00`;
        }
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
      xAxis: data.xAxis,
      yAxis: data.yAxis,
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "line",
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
          datasetId: "filtered"
        }
      ]
    }
  };
}
