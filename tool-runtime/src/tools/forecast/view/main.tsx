/// <reference lib="dom" />
/**
 * The view create_forecast brings (an MCP App): the recent history, the median (P50) and
 * its interval for each day ahead, drawn by Charts; the same figures as a table; and, behind
 * a disclosure, what the forecast rests on and how it did against the last days.
 *
 * It draws only the tool's validated result. A forecast delivered as an image has its own
 * block in the conversation, and this view then takes no room.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Divider } from "@astryxdesign/core/Divider";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Table } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import {
  TableRows,
  ViewFrame,
  chevronDownIcon,
  columnWidth,
  infoIcon,
  numberFormatter,
  pick,
  useHost,
} from "../../../views/kit";
import { init, type EChartsType } from "../../charts/echarts";
import { PALETTE, chartOptions, type ChartStyle } from "../../charts/options";
import { PLOT_TEXTS, forecastPlot, openingZoom } from "../plot";
import "./view.css";

/** What a host passes on of a tool's result; larger results never reach the view. */
const MAX_PAYLOAD_BYTES = 256 * 1024;
const UNZOOMED = { start: 0, end: 100 };
/**
 * The interval stands for about 8 days in 10. With at least 10 days in the check, fewer than
 * 6 in 10 inside is unlikely by chance: the interval is too narrow for this series.
 */
const NARROW = { scored: 10, share: 0.6 };
/** The days ahead are the point: the chart opens on them and the last weeks before them. */
const focus = (data: Payload) => openingZoom(data);

const numbers = z.array(z.number().finite()).max(400);
const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
// A code this view has no words for (from a newer runtime) still shows, in general words.
const unavailable = z.string().max(40);
const payloadSchema = z.object({
  presentation: z.literal("interactive"),
  title: z.string().max(120).optional(),
  model: z.object({ name: z.string().max(80), parameters: z.number().nonnegative() }),
  source: z
    .object({
      filename: z.string().max(260),
      sheet: z.string().max(200).optional(),
      date_column: z.string().max(200),
      value_column: z.string().max(200),
    })
    .optional(),
  history: z.object({
    from: day,
    to: day,
    days: z.number().int().nonnegative(),
    missing: z.number().int().nonnegative(),
    used_from: day.optional(),
    used_days: z.number().int().nonnegative().optional(),
    empty_end_days: z.number().int().nonnegative().optional(),
  }),
  forecast: z.object({ from: day, days: z.number().int().min(1).max(400), p10: numbers, p50: numbers, p90: numbers }),
  recent: z.object({ from: day, values: z.array(z.number().finite().nullable()).max(1000) }),
  holdout: z.union([
    z.object({
      from: day,
      to: day,
      scored: z.number().int().nonnegative(),
      inside: z.number().int().nonnegative(),
      mae: z.number().nonnegative(),
      baseline_mae: z.number().nonnegative(),
    }),
    z.object({ unavailable, reason: z.string().optional() }),
  ]),
});
type Payload = z.infer<typeof payloadSchema>;
type Row = Record<string, unknown>;

const TEXTS = {
  sv: {
    label: "Prognos",
    title: "Prognos",
    reset: "Återställ zoom",
    table: "Tabell",
    legend: "Visa eller dölj serier",
    day: "Dag",
    low: "Lågt (P10)",
    high: "Högt (P90)",
    note: "Prognosen bygger bara på historiken. Väder, lov och helgdagar ingår inte.",
    worse:
      "I testet mot facit träffade prognosen sämre än att upprepa förra veckan. Använd den med försiktighet.",
    narrow: (inside: number, scored: number) =>
      `I testet mot facit låg bara ${inside} av ${scored} dagar inom spannet. Utfallet kan variera mer än spannet visar.`,
    error: "Prognosen kunde inte visas.",
    summary: (days: number, from: string, model: string) => `${days} dagar från ${from} · ${model}`,
    method: "Visa metod",
    hideMethod: "Dölj metod",
    methodLabel: "Metod och underlag",
    rows: {
      source: "Underlag",
      history: "Historik",
      missing: "Saknade värden",
      check: "Test mot facit",
      interval: "Spann",
      ignores: "Tar inte hänsyn till",
      model: "Modell",
    },
    source: (file: string, sheet: string | undefined, date: string, value: string) =>
      `${file}${sheet ? `, blad ${sheet}` : ""}, kolumnerna ${date} och ${value}`,
    history: (range: string, days: number, used: number | undefined, shown: number) =>
      `${range}, ${days} dagar.${used ? ` Modellen läste de senaste ${used}.` : ""} Diagrammet visar de senaste ${shown}.`,
    emptyEnd: (n: number) =>
      `De sista ${n === 1 ? "dagen" : `${n} dagarna`} i filen saknar värde och ingår inte. Prognosen börjar dagen efter det sista värdet.`,
    missing: (n: number) =>
      n === 0 ? "Inga" : `${n} ${n === 1 ? "dag" : "dagar"} utan värde. De räknades som okända, inte som noll.`,
    check: (range: string, inside: number, scored: number, mae: string, baseline: string) =>
      `En prognos för ${range}, gjord på historiken före: ${inside} av ${scored} dagar inom spannet. Medelfel ${mae} per dag, mot ${baseline} om man upprepar förra veckan.`,
    unavailable: {
      SHORT_HISTORY: "Gick inte att göra: historiken före de sista dagarna är för kort.",
      TOO_MANY_MISSING: "Gick inte att göra: för många dagar före de sista dagarna saknar värde.",
      NO_OUTCOME: "Gick inte att göra: de sista dagarna saknar värden att jämföra med.",
      NO_BASELINE: "Gick inte att göra: några veckodagar saknar värde de fyra veckorna före.",
    } as Record<string, string>,
    unavailableOther: "Gick inte att göra för den här historiken.",
    interval: "P10–P90 gäller varje dag för sig. Summera inte gränserna över flera dagar.",
    ignores: "Väder, lov, helgdagar och planerade förändringar",
    model: (name: string, millions: string) => `${name}, ${millions} miljoner parametrar. Körs i er egen miljö.`,
    caveat: "Spannet är modellens bedömning, inte en garanti.",
    describe: (range: string, days: number, start: string) =>
      `Linjediagram: historik ${range} och prognos för ${days} dagar från ${start}, med mittvärdet och spannet P10–P90 för varje dag. Samma siffror finns i tabellen.`,
  },
  en: {
    label: "Forecast",
    title: "Forecast",
    reset: "Reset zoom",
    table: "Table",
    legend: "Show or hide series",
    day: "Day",
    low: "Low (P10)",
    high: "High (P90)",
    note: "The forecast rests on the history only. Weather, school breaks and holidays are not included.",
    worse:
      "In the check against the outcome, the forecast missed by more than repeating last week. Use it with care.",
    narrow: (inside: number, scored: number) =>
      `In the check against the outcome, only ${inside} of ${scored} days fell inside the interval. Outcomes can vary more than the interval shows.`,
    error: "The forecast could not be displayed.",
    summary: (days: number, from: string, model: string) => `${days} days from ${from} · ${model}`,
    method: "Show method",
    hideMethod: "Hide method",
    methodLabel: "Method and data",
    rows: {
      source: "Data",
      history: "History",
      missing: "Missing values",
      check: "Check against the outcome",
      interval: "Interval",
      ignores: "Does not account for",
      model: "Model",
    },
    source: (file: string, sheet: string | undefined, date: string, value: string) =>
      `${file}${sheet ? `, sheet ${sheet}` : ""}, columns ${date} and ${value}`,
    history: (range: string, days: number, used: number | undefined, shown: number) =>
      `${range}, ${days} days.${used ? ` The model read the last ${used}.` : ""} The chart shows the last ${shown}.`,
    emptyEnd: (n: number) =>
      `The last ${n === 1 ? "day" : `${n} days`} in the file ${n === 1 ? "has" : "have"} no value and ${n === 1 ? "is" : "are"} left out. The forecast starts the day after the last value.`,
    missing: (n: number) =>
      n === 0 ? "None" : `${n} ${n === 1 ? "day" : "days"} without a value, read as unknown, not as zero.`,
    check: (range: string, inside: number, scored: number, mae: string, baseline: string) =>
      `A forecast for ${range}, made from the history before: ${inside} of ${scored} days inside the interval. Mean error ${mae} a day, against ${baseline} for repeating last week.`,
    unavailable: {
      SHORT_HISTORY: "Not possible: the history before the last days is too short.",
      TOO_MANY_MISSING: "Not possible: too many days before the last days lack a value.",
      NO_OUTCOME: "Not possible: the last days have no values to compare with.",
      NO_BASELINE: "Not possible: some weekdays lack a value in the four weeks before.",
    } as Record<string, string>,
    unavailableOther: "Not possible for this history.",
    interval: "P10–P90 holds for each day on its own. Do not add the bounds across days.",
    ignores: "Weather, school breaks, holidays and planned changes",
    model: (name: string, millions: string) => `${name}, ${millions} million parameters. Runs in your own environment.`,
    caveat: "The interval is the model's judgement, not a guarantee.",
    describe: (range: string, days: number, start: string) =>
      `Line chart: history ${range} and a forecast of ${days} days from ${start}, with the median and the P10–P90 interval for each day. The same figures are in the table.`,
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

function ForecastView() {
  const [data, setData] = useState<Payload | null>(null);
  const [shown, setShown] = useState(false);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [zoomed, setZoomed] = useState(false);
  const [table, setTable] = useState(false);
  const [open, setOpen] = useState(false);
  const methodId = useId();
  const state = useRef({ selected, zoom: UNZOOMED });
  const plot = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const latest = useRef<Payload | null>(null);
  latest.current = data;

  const host = useHost("eneo-forecast", {
    onResult: (result) => {
      const payload = result.structuredContent as Record<string, unknown> | undefined;
      // A forecast delivered as an image has its own block and must not also show an empty view.
      if (!payload || payload.presentation !== "interactive") {
        setShown(false);
        return;
      }
      try {
        if (JSON.stringify(payload).length > MAX_PAYLOAD_BYTES) throw new Error("Too large");
        const parsed = payloadSchema.parse(payload);
        state.current = { selected: {}, zoom: focus(parsed) };
        setSelected({});
        setZoomed(false);
        setData(parsed);
        setFailed(false);
      } catch {
        setData(null);
        setFailed(true);
      }
      setShown(true);
    },
  });
  const { context } = host;
  const text = pick(context, TEXTS);
  const plotTexts = pick(context, PLOT_TEXTS);
  const locale = context.locale || "sv-SE";
  const dark = context.theme === "dark";
  const format = useMemo(() => numberFormatter(locale), [locale]);
  // Errors are read as sizes, three digits each, so 61,4 stands beside 186 rather than 186,2.
  const error = useMemo(
    () => new Intl.NumberFormat(locale, { maximumSignificantDigits: 3, useGrouping: "min2" }),
    [locale],
  );
  const dates = useMemo(() => {
    const short = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: "UTC" });
    const long = new Intl.DateTimeFormat(locale, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
    // A span names its years, so two years of history do not read as nineteen days.
    const span = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    const at = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
    return {
      short: (iso: string) => short.format(at(iso)),
      long: (iso: string) => long.format(at(iso)),
      range: (from: string, to: string) => span.formatRange(at(from), at(to)),
    };
  }, [locale]);
  const spec = useMemo(() => {
    if (!data) return null;
    const recentTo = new Date(Date.parse(`${data.forecast.from}T00:00:00Z`) - 86_400_000).toISOString().slice(0, 10);
    return {
      ...forecastPlot(data, plotTexts, data.title),
      description: text.describe(dates.range(data.recent.from, recentTo), data.forecast.days, dates.short(data.forecast.from)),
    };
  }, [data, plotTexts, text, dates]);

  useEffect(() => {
    const element = plot.current;
    if (!spec || !element) return;
    if (!chart.current) {
      chart.current = init(element, undefined, { renderer: "svg" });
      chart.current.on("datazoom", (event: unknown) => {
        const zoom = event as { start?: number; end?: number; batch?: { start?: number; end?: number }[] };
        const range = zoom.batch?.[0] ?? zoom;
        if (typeof range.start !== "number" || typeof range.end !== "number") return;
        state.current.zoom = { start: range.start, end: range.end };
        const home = focus(latest.current!);
        setZoomed(Math.abs(range.start - home.start) > 0.01 || Math.abs(range.end - home.end) > 0.01);
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

  const palette = PALETTE[dark ? "dark" : "light"];
  const legend = [
    { name: plotTexts.history, color: palette[0], band: false },
    { name: plotTexts.median, color: palette[1], band: false },
    { name: plotTexts.interval, color: palette[1], band: true },
  ];
  const toggle = (name: string, showing: boolean) => {
    const next = { ...state.current.selected, [name]: showing };
    state.current.selected = next;
    setSelected(next);
    chart.current?.dispatchAction({ type: showing ? "legendSelect" : "legendUnSelect", name });
  };
  // Back to the view the chart opened on, not to the whole history.
  const reset = () => {
    if (!data) return;
    const home = focus(data);
    state.current.zoom = home;
    setZoomed(false);
    chart.current?.dispatchAction({ type: "dataZoom", ...home });
  };

  const figures = useMemo(() => {
    if (!data) return { columns: [], data: [] as Row[] };
    const first = Date.parse(`${data.forecast.from}T00:00:00Z`);
    const rows = data.forecast.p50.map((p50, i) => [
      dates.long(new Date(first + i * 86_400_000).toISOString().slice(0, 10)),
      data.forecast.p10[i],
      p50,
      data.forecast.p90[i],
    ]);
    const headers = [text.day, text.low, plotTexts.median, text.high];
    const cell = (value: unknown) => (typeof value === "number" ? format(value) : String(value ?? "–"));
    return {
      columns: headers.map((header, index) => ({
        key: `c${index}`,
        header,
        align: index === 0 ? ("start" as const) : ("end" as const),
        width: columnWidth(header, rows.map((row) => cell(row[index]))),
        renderCell: (item: Row) => cell(item[index]),
      })),
      data: rows.map((row, index) => ({ ...row, id: index }) as unknown as Row),
    };
  }, [data, dates, format, text, plotTexts]);

  const holdout = data?.holdout;
  const worse = !!holdout && "mae" in holdout && holdout.scored > 0 && holdout.mae > holdout.baseline_mae;
  const narrow =
    !worse && !!holdout && "mae" in holdout && holdout.scored >= NARROW.scored && holdout.inside < NARROW.share * holdout.scored
      ? text.narrow(holdout.inside, holdout.scored)
      : null;

  return (
    <ViewFrame
      host={host}
      name="forecast"
      shown={shown}
      label={text.label}
      title={data?.title || text.title}
      controls={
        data && (
          <>
            <Button variant="ghost" label={text.reset} isDisabled={!zoomed} onClick={reset} />
            <ToggleButton label={text.table} isPressed={table} onPressedChange={setTable} />
          </>
        )
      }
      notices={
        failed ? (
          <Banner status="error" container="section" title={text.error} />
        ) : data ? (
          worse ? (
            <Banner status="warning" container="section" title={text.worse} />
          ) : (
            narrow && <Banner status="warning" container="section" title={narrow} />
          )
        ) : null
      }
      footer={
        data && (
          <div className="eneo-method" data-open={open ? "true" : "false"}>
            <Toolbar
              label={text.methodLabel}
              dividers={["top"]}
              startContent={
                <Text type="supporting" color="secondary">
                  {text.summary(data.forecast.days, dates.short(data.forecast.from), data.model.name)}
                </Text>
              }
              endContent={
                <Button
                  variant="ghost"
                  label={open ? text.hideMethod : text.method}
                  endContent={<span className="eneo-chevron">{chevronDownIcon}</span>}
                  aria-expanded={open}
                  aria-controls={methodId}
                  onClick={() => setOpen((value) => !value)}
                />
              }
            />
            {/* Always rendered so it can grow open; inert while closed, so focus skips it. */}
            <div className="eneo-method-panel" id={methodId} inert={!open}>
              <div className="eneo-method-inner">
                <div className="eneo-method-body">
                <MetadataList label={{ position: "start", width: 168 }}>
                  {data.source && (
                    <MetadataListItem label={text.rows.source}>
                      {text.source(data.source.filename, data.source.sheet, data.source.date_column, data.source.value_column)}
                    </MetadataListItem>
                  )}
                  <MetadataListItem label={text.rows.history}>
                    {text.history(
                      dates.range(data.history.from, data.history.to),
                      data.history.days,
                      data.history.used_days,
                      data.recent.values.length,
                    )}
                    {data.history.empty_end_days ? ` ${text.emptyEnd(data.history.empty_end_days)}` : ""}
                  </MetadataListItem>
                  <MetadataListItem label={text.rows.missing}>{text.missing(data.history.missing)}</MetadataListItem>
                  <MetadataListItem label={text.rows.check}>
                    {"mae" in data.holdout
                      ? text.check(
                          dates.range(data.holdout.from, data.holdout.to),
                          data.holdout.inside,
                          data.holdout.scored,
                          error.format(data.holdout.mae),
                          error.format(data.holdout.baseline_mae),
                        )
                      : (text.unavailable[data.holdout.unavailable] ?? text.unavailableOther)}
                  </MetadataListItem>
                  <MetadataListItem label={text.rows.interval}>{text.interval}</MetadataListItem>
                  <MetadataListItem label={text.rows.ignores}>{text.ignores}</MetadataListItem>
                  <MetadataListItem label={text.rows.model}>
                    {text.model(data.model.name, format(Math.round(data.model.parameters / 100_000) / 10))}
                  </MetadataListItem>
                </MetadataList>
                <Text type="supporting" color="secondary">
                  {text.caveat}
                </Text>
                </div>
              </div>
            </div>
          </div>
        )
      }
    >
      {data && (
        <div role="group" aria-label={text.legend} className="eneo-legend">
          {legend.map(({ name, color, band }) => {
            const showing = selected[name] !== false;
            const dot = (
              <span
                className="eneo-dot"
                data-band={band ? "" : undefined}
                data-showing={showing ? "" : undefined}
                style={{ "--series": color } as React.CSSProperties}
              />
            );
            return (
              <ToggleButton
                key={name}
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
      <div ref={plot} className="eneo-plot" hidden={!data} />
      {/* What the forecast cannot know, said once beside it rather than as an alert. */}
      {data && (
        <p className="eneo-note">
          {infoIcon}
          <Text type="supporting" color="secondary">
            {text.note}
          </Text>
        </p>
      )}
      {data && table && (
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

createRoot(document.getElementById("app")!).render(<ForecastView />);
