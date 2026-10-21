/// <reference lib="dom" />
/**
 * The view create_chart brings (an MCP App): the chart with values under the pointer, series
 * the reader can hide, an x axis they can zoom, and the same figures as a table.
 *
 * It draws only validated chart data. A chart delivered as an image has its own block in the
 * conversation, and this view then takes no room.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Divider } from "@astryxdesign/core/Divider";
import { Table } from "@astryxdesign/core/Table";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { TableRows, ViewFrame, columnWidth, pick, useHost } from "../../../views/kit";
import { init, type EChartsType } from "../echarts";
import { PALETTE, chartOptions, type ChartStyle } from "../options";
import { chartSpecSchema, validateChartSpec, type ChartSpec } from "../spec";
import "./view.css";

/** What a host passes on of a tool's result; larger chart data never reaches the view. */
const MAX_PAYLOAD_BYTES = 256 * 1024;
const MAX_POINTS = 20_000;
const UNZOOMED = { start: 0, end: 100 };

type Row = Record<string, unknown>;

const TEXTS = {
  sv: {
    label: "Diagram",
    title: "Diagram",
    reset: "Återställ zoom",
    table: "Tabell",
    legend: "Visa eller dölj serier",
    category: "Kategori",
    series: "Serie",
    error: "Diagrammet kunde inte visas.",
  },
  en: {
    label: "Chart",
    title: "Chart",
    reset: "Reset zoom",
    table: "Table",
    legend: "Show or hide series",
    category: "Category",
    series: "Series",
    error: "The chart could not be displayed.",
  },
};

/** A theme colour as the browser resolves it where `element` stands. */
function themeColor(element: HTMLElement, token: string): string {
  const probe = document.createElement("span");
  probe.style.color = `var(${token})`;
  element.append(probe);
  const color = getComputedStyle(probe).color;
  probe.remove();
  return color;
}

function ChartView() {
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  const [shown, setShown] = useState(false);
  const [failed, setFailed] = useState(false);
  const [resultLocale, setResultLocale] = useState<string>();
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [zoomed, setZoomed] = useState(false);
  const [table, setTable] = useState(false);
  // What the reader has chosen, kept beside the chart so redrawing it does not undo them.
  const state = useRef({ selected, zoom: UNZOOMED });
  const plot = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);

  const host = useHost("eneo-chart", {
    onResult: (result) => {
      const payload = result.structuredContent as Record<string, unknown> | undefined;
      // A chart delivered as an image has its own block and must not also show an empty view.
      if (!payload || payload.presentation !== "interactive") {
        setShown(false);
        return;
      }
      try {
        if (JSON.stringify(payload).length > MAX_PAYLOAD_BYTES) throw new Error("Too large");
        const parsed = chartSpecSchema.parse(payload.chart);
        validateChartSpec(parsed, MAX_POINTS);
        state.current = { selected: {}, zoom: UNZOOMED };
        setSelected({});
        setZoomed(false);
        setResultLocale(typeof payload.locale === "string" ? payload.locale : undefined);
        setSpec(parsed);
        setFailed(false);
      } catch {
        setSpec(null);
        setFailed(true);
      }
      setShown(true);
    },
  });
  const { context } = host;
  const text = pick(context, TEXTS);
  const locale = context.locale || resultLocale || "en-GB";
  const dark = context.theme === "dark";

  useEffect(() => {
    const element = plot.current;
    if (!spec || !element) return;
    if (!chart.current) {
      chart.current = init(element, undefined, { renderer: "svg" });
      chart.current.on("datazoom", (event: unknown) => {
        const zoom = event as {
          start?: number;
          end?: number;
          batch?: { start?: number; end?: number }[];
        };
        const range = zoom.batch?.[0] ?? zoom;
        if (typeof range.start !== "number" || typeof range.end !== "number") return;
        state.current.zoom = { start: range.start, end: range.end };
        setZoomed(range.start !== 0 || range.end !== 100);
      });
    }
    const style: ChartStyle = {
      dark,
      locale,
      ink: themeColor(element, "--color-text-primary"),
      inkSecondary: themeColor(element, "--color-text-secondary"),
      grid: themeColor(element, "--color-border"),
      axis: themeColor(element, "--color-border-emphasized"),
      surface: themeColor(element, "--color-background-surface"),
      font: getComputedStyle(element).fontFamily,
      textSize: 12,
    };
    chart.current.setOption(chartOptions(spec, style, state.current), { notMerge: true });
    chart.current.resize();
  }, [spec, dark, locale]);

  useEffect(() => {
    const element = plot.current;
    if (!element) return;
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  const colors = PALETTE[dark ? "dark" : "light"];
  // A single series is named by the title and has nothing to hide behind.
  const names = !spec
    ? []
    : spec.type === "pie"
      ? spec.labels
      : spec.series.length > 1
        ? spec.series.map((s) => s.name)
        : [];
  const toggle = (name: string, showing: boolean) => {
    // A plain object with own properties also handles labels such as __proto__ safely.
    const next = { ...state.current.selected, [name]: showing };
    state.current.selected = next;
    setSelected(next);
    chart.current?.dispatchAction({ type: showing ? "legendSelect" : "legendUnSelect", name });
  };
  const reset = () => {
    state.current.zoom = UNZOOMED;
    setZoomed(false);
    chart.current?.dispatchAction({ type: "dataZoom", ...UNZOOMED });
  };

  const figures = useMemo(() => {
    if (!spec) return { columns: [], data: [] as Row[] };
    const format = new Intl.NumberFormat(locale, { maximumFractionDigits: 12 });
    const scatter = spec.type === "scatter";
    const headers = scatter
      ? [text.series, spec.x_label || "x", spec.y_label || spec.unit || "y"]
      : [spec.x_label || text.category, ...spec.series.map((s) => s.name)];
    const rows = scatter
      ? spec.series.flatMap((s) => s.values.map((value, i) => [s.name, s.x![i], value]))
      : spec.labels.map((label, i) => [label, ...spec.series.map((s) => s.values[i])]);
    const shown = (value: unknown) =>
      value === null || value === undefined
        ? "–"
        : typeof value === "number"
          ? format.format(value)
          : String(value);
    return {
      columns: headers.map((header, index) => ({
        key: `c${index}`,
        header,
        // The first column names the row; every other one is a figure.
        align: index === 0 ? ("start" as const) : ("end" as const),
        width: columnWidth(
          header,
          rows.map((row) => shown(row[index])),
        ),
        renderCell: (item: Row) => shown(item[index]),
      })),
      data: rows.map((row, index) => ({ ...row, id: index }) as unknown as Row),
    };
  }, [spec, locale, text]);

  return (
    <ViewFrame
      host={host}
      name="chart"
      shown={shown}
      label={text.label}
      title={spec?.title || text.title}
      controls={
        spec && (
          <>
            {spec.type !== "pie" && (
              <Button variant="ghost" label={text.reset} isDisabled={!zoomed} onClick={reset} />
            )}
            <ToggleButton label={text.table} isPressed={table} onPressedChange={setTable} />
          </>
        )
      }
      notices={failed && <Banner status="error" container="section" title={text.error} />}
    >
      {names.length > 0 && (
        <div role="group" aria-label={text.legend} className="eneo-legend">
          {names.map((name, index) => {
            const showing = selected[name] !== false;
            const dot = (
              <span
                className="eneo-dot"
                data-showing={showing ? "" : undefined}
                style={{ "--series": colors[index % colors.length] } as React.CSSProperties}
              />
            );
            return (
              <ToggleButton
                key={`${index}-${name}`}
                size="sm"
                label={name}
                icon={dot}
                isPressed={showing}
                onPressedChange={(next) => toggle(name, next)}
              />
            );
          })}
        </div>
      )}
      <div ref={plot} className="eneo-plot" hidden={!spec} />
      {spec && table && (
        <>
          <Divider />
          <Table<Row>
            data={figures.data}
            columns={figures.columns}
            idKey="id"
            density="compact"
            dividers="rows"
            scrollWrapper={TableRows}
          />
        </>
      )}
    </ViewFrame>
  );
}

createRoot(document.getElementById("app")!).render(<ChartView />);
