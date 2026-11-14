import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { Popover } from "@astryxdesign/core/Popover";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "use-intl";
import { useLayoutEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";

/**
 * The composer's panel pills (Verktyg, Skills): icon, label (icon-only on phones) and count.
 * A space between label and count keeps them two words for axe, whose check that the name
 * ("Verktyg: 2 av 3 aktiva") holds the label joins text with no separator (WCAG 2.5.3).
 */
const PILL_CLASS =
  "text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring aria-expanded:bg-ax-hover inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11 pointer-coarse:min-w-11";
export const COMPOSER_COUNT_CLASS =
  "bg-ax-muted text-ax-text flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[11px] tabular-nums";

/** Where a panel's content is shown: beside its pill, or in a phone's sheet. */
export type ComposerPanelSurface = {
  /** In the bottom sheet: one column, touch-sized rows, its own padding. */
  stacked: boolean;
  /** The popover's pill, for content that must fit in the room above it. */
  anchor?: HTMLElement | null;
  /** The sheet's visible close button; the popover has its own. */
  onClose?: () => void;
};

/**
 * What Astryx's Popover adds around its content, above the trigger: the 4 px
 * gap, 12 px of padding above and below and the 16 px gutter at the top of
 * the window.
 */
const POPOVER_CHROME = 44;

/**
 * A ref for a panel that keeps it within the room above its trigger.
 * Astryx caps a popover to the window, not to that room, so where the
 * composer sits mid-page (the start state) a long list grew over the pill
 * and the composer; the list scrolls inside instead, and the header and
 * links stay in view.
 */
export function useFitAbove(trigger?: HTMLElement | null) {
  const panel = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = panel.current;
    if (!element || !trigger) return;
    const fit = () => {
      const room = trigger.getBoundingClientRect().top - POPOVER_CHROME;
      element.style.maxHeight = `${Math.max(0, room)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, true);
    return () => {
      window.removeEventListener("resize", fit);
      window.removeEventListener("scroll", fit, true);
    };
  }, [trigger]);
  return panel;
}

/** What a pill shows: an icon, a label and a count, or content of its own. */
type PillFace =
  | { icon: LucideIcon; text: string; count?: number | null; face?: undefined }
  | { face: ReactNode; icon?: undefined; text?: undefined; count?: undefined };

/**
 * A composer pill that opens its panel as a popover above it, or as a bottom
 * sheet on a phone, where a popover anchored to an icon has no room. The
 * popover's content is mounted only while open, so a closed one holds no controls.
 */
export function ComposerPanel({
  icon: Icon,
  text,
  count,
  face,
  name,
  busy = false,
  label,
  open,
  onOpenChange,
  width,
  alignment = "start",
  sheetHeight,
  children
}: PillFace & {
  /** The pill's accessible name: what it shows, with what is on. */
  name: string;
  /** A choice made in the panel is still being saved. */
  busy?: boolean;
  /** Names the popover and the sheet. */
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  width: number;
  /** The popover's edge that lines up with the pill's. */
  alignment?: "start" | "end";
  sheetHeight: ComponentProps<typeof BottomSheet>["height"];
  children: (surface: ComposerPanelSurface) => ReactNode;
}) {
  const t = useTranslations();
  // Held in state, not a ref: the panel's content measures against it.
  const [pillElement, setPillElement] = useState<HTMLButtonElement | null>(null);
  // The composer's toolbar goes icon-only below 40rem (max-sm); so does this.
  const wide = useMediaQuery("(min-width: 40rem)");

  const pill = (props: { onClick?: () => void }) => (
    <button
      ref={setPillElement}
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={name}
      aria-busy={busy || undefined}
      className={PILL_CLASS}
      {...props}
    >
      {Icon ? (
        <>
          <Icon aria-hidden="true" className="size-[15px]" />
          <span className="max-sm:sr-only">{text}</span>{" "}
          {count != null && (
            <span aria-hidden="true" className={COMPOSER_COUNT_CLASS}>
              {count}
            </span>
          )}
        </>
      ) : (
        face
      )}
    </button>
  );

  if (wide) {
    return (
      <Popover
        isOpen={open}
        onOpenChange={onOpenChange}
        placement="above"
        alignment={alignment}
        width={width}
        label={label}
        closeButtonLabel={t("close")}
        content={open ? children({ stacked: false, anchor: pillElement }) : null}
      >
        {pill({})}
      </Popover>
    );
  }
  return (
    <>
      {pill({ onClick: () => onOpenChange(true) })}
      <BottomSheet
        isOpen={open}
        onOpenChange={onOpenChange}
        label={label}
        height={sheetHeight}
        padding={0}
      >
        {children({ stacked: true, onClose: () => onOpenChange(false) })}
      </BottomSheet>
    </>
  );
}
