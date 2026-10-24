"use client";

import {
  Table as AstryxTable,
  useTableStickyColumns,
  type TablePlugin,
  type TableProps as AstryxTableProps
} from "@astryxdesign/core/Table";
import { useMemo, type Ref, type RefCallback } from "react";

/** A table's accessible name: its own label, or the id of what names it. */
type TableName =
  | { "aria-label": string; "aria-labelledby"?: never }
  | { "aria-labelledby": string; "aria-label"?: never };

export type TableProps<T extends Record<string, unknown>> = AstryxTableProps<T> &
  TableName & {
    ref?: Ref<HTMLTableElement>;
    /**
     * Key of the column that stays in view while the rest scrolls sideways,
     * with the columns before it (a selection checkbox): what names a row
     * (decision 9).
     */
    pinnedColumn?: string;
  };

/**
 * Astryx Table that has to be named, and whose scroll region carries that
 * name. Astryx names every table's horizontal scroll region "Tabell", so a
 * keyboard user tabbing to a table that scrolls heard only that; the region
 * now takes the table's own name through Astryx's plugin API. Lint sends
 * every Table import here.
 *
 * `pinnedColumn` holds a column in view (Astryx's sticky columns). It covers
 * what scrolls under it, so the controls in the table keep a scroll margin as
 * wide as the pinned columns: focus moved back to one scrolled out of view
 * comes to rest beside them, not hidden behind them (WCAG 2.4.11). A margin
 * only places what has to scroll into view, so focus on a pinned control,
 * always in view, leaves the scroll where it is (scroll padding on the
 * region would not).
 */
export function Table<T extends Record<string, unknown>>({
  pinnedColumn,
  ...props
}: TableProps<T>) {
  const label = props["aria-label"];
  const labelledBy = props["aria-labelledby"];
  const userPlugins = props.plugins;
  const sticky = useTableStickyColumns<T>({
    startKeys: pinnedColumn ? [pinnedColumn] : undefined
  });
  const plugins = useMemo(() => {
    const scrollRegionName: TablePlugin<T> = {
      transformScrollWrapper: (render) => ({
        ...render,
        htmlProps: {
          ...render.htmlProps,
          ...(labelledBy ? { "aria-labelledby": labelledBy } : { "aria-label": label })
        }
      })
    };
    if (!pinnedColumn) return { ...userPlugins, scrollRegionName };
    // After the sticky plugin, whose ref on the region this one wraps. The
    // attribute is for globals.css section 9.
    const keepFocusClear: TablePlugin<T> = {
      transformScrollWrapper: (render) => ({
        ...render,
        htmlProps: { ...render.htmlProps, ref: measurePinned(render.htmlProps.ref), ...PINNED }
      })
    };
    return { ...userPlugins, sticky, keepFocusClear, scrollRegionName };
  }, [label, labelledBy, pinnedColumn, sticky, userPlugins]);

  return <AstryxTable<T> {...props} plugins={plugins} />;
}

const PINNED = { "data-pinned": "" };

/**
 * The scroll region's ref: passes the region on to `inner` and keeps
 * `--table-pinned-width` at the pinned columns' width (the header cells
 * Astryx offsets): the scroll margin of the table's controls.
 */
function measurePinned(inner: Ref<HTMLDivElement> | undefined): RefCallback<HTMLDivElement> {
  const pass = (node: HTMLDivElement | null) => {
    if (typeof inner === "function") inner(node);
    else if (inner) inner.current = node;
  };
  return (region) => {
    pass(region);
    if (!region) return;
    const measure = () => {
      const start = region.getBoundingClientRect().left;
      let end = start;
      for (const cell of region.querySelectorAll<HTMLElement>("thead th")) {
        if (cell.style.insetInlineStart) end = Math.max(end, cell.getBoundingClientRect().right);
      }
      region.style.setProperty("--table-pinned-width", `${end - start}px`);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(region);
    measure();
    return () => {
      observer.disconnect();
      pass(null);
    };
  };
}
