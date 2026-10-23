"use client";

import {
  Table as AstryxTable,
  type TablePlugin,
  type TableProps as AstryxTableProps
} from "@astryxdesign/core/Table";
import { useMemo, type Ref } from "react";

/** A table's accessible name: its own label, or the id of what names it. */
type TableName =
  | { "aria-label": string; "aria-labelledby"?: never }
  | { "aria-labelledby": string; "aria-label"?: never };

export type TableProps<T extends Record<string, unknown>> = AstryxTableProps<T> &
  TableName & { ref?: Ref<HTMLTableElement> };

/**
 * Astryx Table that has to be named, and whose scroll region carries that
 * name. Astryx names every table's horizontal scroll region "Tabell", so a
 * keyboard user tabbing to a table that scrolls heard only that; the region
 * now takes the table's own name through Astryx's plugin API. Lint sends
 * every Table import here.
 */
export function Table<T extends Record<string, unknown>>(props: TableProps<T>) {
  const label = props["aria-label"];
  const labelledBy = props["aria-labelledby"];
  const userPlugins = props.plugins;
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
    return { ...userPlugins, scrollRegionName };
  }, [label, labelledBy, userPlugins]);

  return <AstryxTable<T> {...props} plugins={plugins} />;
}
