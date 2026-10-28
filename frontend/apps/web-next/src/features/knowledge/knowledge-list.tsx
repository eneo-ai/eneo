"use client";

import { Button } from "@astryxdesign/core/Button";
import { List, ListItem } from "@astryxdesign/core/List";
import { ChevronRight, FolderClosed, Globe, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useRef, type ReactNode } from "react";
import type { TableName } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel } from "@/components/composites/status-label";
import { useFocusAcrossLayouts } from "@/lib/hooks/use-focus-across-layouts";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { VendorIcon } from "./integrations/vendor";
import { rowNeedsStatus, type KnowledgeRow } from "./knowledge-rows";

/** A row and its menu, as its table shows it (a menu that renders nothing leaves a chevron). */
export type KnowledgeItem = { row: KnowledgeRow; actions: ReactNode };

type RowsProps = {
  items: KnowledgeItem[];
  /** Its embedding model's heading, or the source (its tab, or its name on a phone). */
  name: TableName;
  /** What shows when nothing matches the filter. */
  empty?: ReactNode;
};

/** A row's decorative tile: the source's type, or an integration's vendor. */
function RowTile({ row }: { row: KnowledgeRow }) {
  const { source } = row;
  const vendor =
    source.kind === "integration"
      ? source.item.integration_type
      : source.kind === "wrapper"
        ? source.items[0]?.integration_type
        : undefined;
  const Icon =
    source.kind === "collection" ? FolderClosed : source.kind === "website" ? Globe : Plug;
  return (
    <span
      aria-hidden="true"
      className="bg-ax-muted text-ax-text-secondary rounded-ax-element flex size-10 shrink-0 items-center justify-center"
    >
      {vendor ? <VendorIcon type={vendor} size={20} /> : <Icon className="size-5" />}
    </span>
  );
}

/**
 * A knowledge source's items as list rows (decision 9, the artifact's Kunskap
 * board): name, then what it holds and when it changed, then its state only
 * when that needs attention. The whole row opens the item (globals.css 12b);
 * at the end sit "Åtgärda" when it needs a fix, and its menu or a chevron.
 */
export function KnowledgeRows({ items, name, empty }: RowsProps) {
  const t = useTranslations();
  if (items.length === 0) return empty ?? null;
  return (
    <List hasDividers edgeCompensation="inline" {...name}>
      {items.map(({ row, actions }) => {
        const { updatedAt } = row;
        const meta = [
          row.content ? t(row.content.key, row.content.values) : null,
          updatedAt
            ? t.rich("space_updated_on", {
                date: () => <ClientTime value={updatedAt} format="date" />
              })
            : null
        ].filter(Boolean);
        return (
          <ListItem
            key={row.key}
            href={row.href}
            // Name and meta wrap: at large text a truncated line would lose them.
            label={<span className="block font-semibold break-words">{row.name}</span>}
            description={
              <span className="flex min-w-0 flex-col gap-0.5">
                {meta.length > 0 ? (
                  // "uppdaterad" opens the line when nothing comes before it.
                  <span className="block break-words tabular-nums first-letter:uppercase">
                    {meta.map((part, index) => (
                      <Fragment key={index}>
                        {index > 0 ? " · " : null}
                        {part}
                      </Fragment>
                    ))}
                  </span>
                ) : null}
                {rowNeedsStatus(row) ? (
                  <StatusLabel
                    status={row.status.tone}
                    label={t(row.status.labelKey)}
                    isPulsing={row.status.isPulsing}
                  />
                ) : null}
              </span>
            }
            startContent={<RowTile row={row} />}
            endContent={
              <span className="flex items-center gap-2">
                {row.status.fixHref ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    href={row.status.fixHref}
                    label={t("space_fix_named", { name: row.name })}
                  >
                    {t("space_fix")}
                  </Button>
                ) : null}
                <span className="peer contents">{actions}</span>
                <ChevronRight
                  aria-hidden="true"
                  className="text-ax-text-secondary hidden size-4 peer-empty:block"
                />
              </span>
            }
          />
        );
      })}
    </List>
  );
}

/**
 * Rows on a phone, the table (`children`) from 768 px. Both render until the
 * width is known (CSS shows one from the server render); a turn across
 * 768 px keeps focus on the same item.
 */
export function RowsOrTable({ children, ...rows }: RowsProps & { children: ReactNode }) {
  const phone = useMediaMatch(PHONE_QUERY);
  const box = useRef<HTMLDivElement>(null);
  useFocusAcrossLayouts(box, phone);
  return (
    <div ref={box} className="contents">
      {phone !== false ? (
        <div className="md:hidden">
          <KnowledgeRows {...rows} />
        </div>
      ) : null}
      {phone !== true ? <div className="max-md:hidden">{children}</div> : null}
    </div>
  );
}
