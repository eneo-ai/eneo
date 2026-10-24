"use client";

import {
  Table as AstryxTable,
  useTableStickyColumns,
  type TablePlugin,
  type TableProps as AstryxTableProps
} from "@astryxdesign/core/Table";
import { useMemo, type Ref, type RefCallback } from "react";

/** A table's (or list's) accessible name: its own label, or the id of what names it. */
export type TableName =
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
 * what scrolls under it, so a control there that takes focus is moved out
 * from under it (WCAG 2.4.11): see `keepFocusClear`.
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
    const pinnedRegion: TablePlugin<T> = {
      transformScrollWrapper: (render) => ({
        ...render,
        htmlProps: { ...render.htmlProps, ref: keepFocusClear(render.htmlProps.ref), ...PINNED }
      })
    };
    return { ...userPlugins, sticky, pinnedRegion, scrollRegionName };
  }, [label, labelledBy, pinnedColumn, sticky, userPlugins]);

  return <AstryxTable<T> {...props} plugins={plugins} />;
}

const PINNED = { "data-pinned": "" };

/**
 * The scroll region's ref: passes the region on to `inner`, and moves what
 * takes focus in a scrolling column out from under the pinned columns (the
 * header cells Astryx offsets mark how far they reach). A pinned control is
 * always in view and moves nothing. This runs before the browser scrolls
 * focus into view, which then has nothing left to do. CSS cannot do it: the
 * browser counts a control under the pinned columns as visible, so a scroll
 * margin never applies, and scroll padding also moved the table whenever a
 * pinned control took focus.
 */
function keepFocusClear(inner: Ref<HTMLDivElement> | undefined): RefCallback<HTMLDivElement> {
  const pass = (node: HTMLDivElement | null) => {
    if (typeof inner === "function") inner(node);
    else if (inner) inner.current = node;
  };
  return (region) => {
    pass(region);
    if (!region) return;
    const onFocusIn = (event: FocusEvent) => {
      const cell = (event.target as Element).closest<HTMLElement>("td, th");
      if (!cell || cell.style.insetInlineStart) return;
      let pinnedEnd = region.getBoundingClientRect().left;
      for (const header of region.querySelectorAll<HTMLElement>("thead th")) {
        if (header.style.insetInlineStart) {
          pinnedEnd = Math.max(pinnedEnd, header.getBoundingClientRect().right);
        }
      }
      const covered = pinnedEnd - (event.target as Element).getBoundingClientRect().left;
      if (covered > 0) region.scrollLeft -= covered;
    };
    region.addEventListener("focusin", onFocusIn);
    return () => {
      region.removeEventListener("focusin", onFocusIn);
      pass(null);
    };
  };
}
