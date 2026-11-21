import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "use-intl";
import { useState, type ReactNode } from "react";
import { IconTile } from "@/components/composites/icon-tile";

/** The lines a value folds to until "Visa hela", and the characters of text. */
export const FOLDED_LINES = 4;
const FOLDED_CHARS = 200;

// ponytail: length heuristic, not a measurement; measure the clamp if a
// short value ever shows "Visa hela" without anything more to show.
/** Whether a text is long enough to fold until "Visa hela". */
export function isLongText(text: string): boolean {
  return text.length > FOLDED_CHARS || text.split("\n").length > FOLDED_LINES;
}

/** Compact disclosure rows in a card, as the chat's activity disclosures have. */
export const HELPER_CARD_COLLAPSIBLE_CLASS =
  "[&_.astryx-collapsible-trigger]:min-h-8 [&_.astryx-collapsible-trigger]:text-[13px] [&_.astryx-collapsible-trigger]:font-medium";

/**
 * The frame of a card a helper chat draws in an answer for a change its
 * tools made or proposed: a tile, the title (the card's name), an optional
 * status at the end of the title row, then the card's content.
 */
export function HelperCardFrame({
  label,
  icon,
  status,
  children
}: {
  label: string;
  /** A lucide-react icon; sized by the tile. */
  icon: ReactNode;
  /** A short state beside the title ("Inte sparat"). */
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="border-ax-border bg-ax-sunken rounded-ax-container flex w-full flex-col gap-3 border p-3.5 font-sans"
    >
      <div className="flex items-center gap-2.5">
        <IconTile size="sm" hue="blue" icon={icon} />
        <h3 className="m-0 text-[13.5px] font-semibold">{label}</h3>
        {status ? <span className="ms-auto shrink-0">{status}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** "Visa hela" / "Visa mindre": unfolds a value folded to a few lines, and folds it again. */
export function FoldButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const t = useTranslations();
  return (
    <Button
      size="sm"
      variant="ghost"
      label={open ? t("flows_change_card_show_less") : t("flows_change_card_show_all")}
      onClick={onToggle}
    />
  );
}

/**
 * One changed value under its name, before and after. A long one (`long`)
 * folds to a few lines until "Visa hela"; each side is drawn by the card,
 * told whether it is folded.
 */
export function FieldBeforeAfter({
  label,
  long,
  before,
  after
}: {
  label: string;
  long: boolean;
  before: (folded: boolean) => ReactNode;
  after: (folded: boolean) => ReactNode;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const folded = long && !open;
  return (
    <li className="flex flex-col gap-1">
      <p className="text-ax-text-secondary m-0 text-xs font-semibold">{label}</p>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-ax-text-tertiary">{t("flows_change_card_before")}</dt>
        <dd className="text-ax-text-secondary m-0 min-w-0 break-words whitespace-pre-wrap">
          {before(folded)}
        </dd>
        <dt className="text-ax-text-tertiary">{t("flows_change_card_after")}</dt>
        <dd className="text-ax-text m-0 min-w-0 break-words whitespace-pre-wrap">
          {after(folded)}
        </dd>
      </dl>
      {long ? (
        <div>
          <FoldButton open={open} onToggle={() => setOpen((value) => !value)} />
        </div>
      ) : null}
    </li>
  );
}
