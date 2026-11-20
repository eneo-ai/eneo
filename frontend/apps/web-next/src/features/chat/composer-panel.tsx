import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { useMergedRefs } from "@astryxdesign/core/hooks";
import { Popover } from "@astryxdesign/core/Popover";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "use-intl";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type Ref,
  type ReactNode
} from "react";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";

/**
 * The composer's panel pills (Verktyg, Skills): icon, label (icon-only on phones) and count.
 * A space between label and count keeps them two words for axe, whose check that the name
 * ("Verktyg: 2 av 3 aktiva") holds the label joins text with no separator (WCAG 2.5.3).
 */
const PILL_CLASS =
  "text-ax-text-secondary hover:bg-ax-hover hover:text-ax-text focus-visible:outline-ring aria-expanded:bg-ax-hover inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11 pointer-coarse:min-w-11";
/** A count: Astryx's neutral badge fill, a tint that shows on the composer and the tabs in both themes. */
export const COMPOSER_COUNT_CLASS =
  "bg-ax-selected text-ax-text flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[11px] tabular-nums";

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
 * gap and 12 px of padding above and below. It also keeps 16 px from the
 * window's top (WINDOW_GUTTER).
 */
const POPOVER_CHROME = 28;
const WINDOW_GUTTER = 16;

/**
 * A ref for a panel that keeps it within the room above its trigger, up to the
 * window's top margin. Astryx caps a popover to the window, not to that room,
 * so where the composer sits mid-page (the start state) a long list grew over
 * the pill and the composer; the list scrolls inside instead, and the panel's
 * header and links stay in view. The room is not cut at the chat's header
 * (Chatt, Historik): a list that fits in the window never scrolls, and the
 * panel covers the header while it is open.
 *
 * The panel's height follows its content, but never shrinks while it is open
 * (within that room): a search that shortens a list, or a tab with less in
 * it, would otherwise move the panel's top, and its tabs, under the pointer.
 */
export function useFitAbove(trigger?: HTMLElement | null) {
  const panel = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = panel.current;
    if (!element || !trigger) return;
    let room = 0;
    let held = 0;
    const apply = () => {
      element.style.maxHeight = `${room}px`;
      element.style.minHeight = `${Math.min(held, room)}px`;
    };
    const fit = () => {
      room = Math.max(0, trigger.getBoundingClientRect().top - WINDOW_GUTTER - POPOVER_CHROME);
      apply();
    };
    const observer = new ResizeObserver(([entry]) => {
      const height = entry?.borderBoxSize[0]?.blockSize ?? 0;
      if (height > held) {
        held = height;
        apply();
      }
    });
    // The pill moves when the page around it changes size, as the start state's centred
    // column does when its lists or the context meter come in; a move has no event of its
    // own, so the room is measured again whenever one of the pill's ancestors resizes.
    const around = new ResizeObserver(fit);
    for (
      let node = trigger.parentElement;
      node && node !== document.body;
      node = node.parentElement
    )
      around.observe(node);
    fit();
    observer.observe(element);
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, true);
    return () => {
      around.disconnect();
      observer.disconnect();
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

/** The chosen tab of a tab, or the checked radio of a radio's group, when it is another. */
function chosenInstead(control: HTMLElement, panel: HTMLElement): HTMLElement | null {
  if (control.getAttribute("role") === "tab" && control.getAttribute("aria-selected") !== "true") {
    return (
      control
        .closest('[role="tablist"]')
        ?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]') ?? null
    );
  }
  if (control instanceof HTMLInputElement && control.type === "radio" && !control.checked) {
    return (
      [...panel.querySelectorAll<HTMLInputElement>('input[type="radio"]:checked')].find(
        (radio) => radio.name === control.name
      ) ?? null
    );
  }
  return null;
}

/**
 * A panel's content. Astryx's ChatComposer focuses its field on a click that
 * reaches it outside a button, and a click in a panel reaches it through
 * React's tree (an arrow key on a radio is a click too): stopped here, focus
 * stays on the control the click was on. Closing on a click outside is the
 * popover's and the sheet's own, and still works.
 *
 * The popover focuses its first control as it opens: the first tab or radio,
 * chosen or not. That first focus goes to the chosen one instead, the single
 * tab stop of a tab list and of a radio group. The sheet focuses its own
 * surface, so it passes no control over.
 */
function PanelContent({ children, popover }: { children: ReactNode; popover: boolean }) {
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = content.current;
    if (!element || !popover) return;
    const toChosen = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement) chosenInstead(event.target, element)?.focus();
    };
    element.addEventListener("focusin", toChosen, { once: true });
    return () => element.removeEventListener("focusin", toChosen);
  }, [popover]);
  return (
    <div
      ref={content}
      role="presentation"
      className="contents"
      onClick={(event) => event.stopPropagation()}
    >
      {children}
    </div>
  );
}

/**
 * A composer pill that opens its panel as a popover above it, or as a bottom
 * sheet in a phone's layout (`usePhoneScreen`, as the rest of the app), where a
 * popover anchored to an icon has no room. The surface is chosen as the panel
 * opens and kept until it closes, so a phone turned with the panel open keeps
 * it. Astryx's Popover chooses per opening too, but its sheet is always tall
 * and the content cannot tell which surface it is on. The popover's content
 * is mounted only while open, so a closed one holds no controls.
 */
export function ComposerPanel({
  icon: Icon,
  text,
  count,
  face,
  name,
  busy = false,
  disabled = false,
  triggerRef,
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
  disabled?: boolean;
  triggerRef?: Ref<HTMLButtonElement>;
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
  // The sheet gives focus back to the pill when it closes (Safari would leave it elsewhere).
  const pillRef = useRef<HTMLButtonElement>(null);
  const pillRefs = useMergedRefs(pillRef, setPillElement, triggerRef);
  const phone = usePhoneScreen();
  const [openedAsSheet, setOpenedAsSheet] = useState<boolean | null>(null);
  // Latched in render, as the panel opens and closes, so the opening render has its surface.
  if (open && openedAsSheet === null) setOpenedAsSheet(phone);
  if (!open && openedAsSheet !== null) setOpenedAsSheet(null);
  const sheet = openedAsSheet ?? phone;

  const pill = (props: { onClick?: () => void }) => (
    <button
      ref={pillRefs}
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={name}
      aria-busy={busy || undefined}
      aria-disabled={disabled || undefined}
      className={PILL_CLASS}
      {...props}
    >
      {Icon ? (
        <>
          <Icon aria-hidden="true" className="size-[15px]" />
          {/* The composer's toolbar goes icon-only below 40rem (max-sm); so does this. */}
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

  if (!sheet) {
    return (
      <Popover
        isOpen={open}
        onOpenChange={(next) => {
          if (!next || !disabled) onOpenChange(next);
        }}
        placement="above"
        alignment={alignment}
        width={width}
        label={label}
        closeButtonLabel={t("close")}
        content={
          open ? (
            <PanelContent popover>{children({ stacked: false, anchor: pillElement })}</PanelContent>
          ) : null
        }
      >
        {pill({})}
      </Popover>
    );
  }
  return (
    <>
      {pill({
        onClick: () => {
          if (!disabled) onOpenChange(true);
        }
      })}
      <BottomSheet
        isOpen={open}
        onOpenChange={(next) => {
          if (!next || !disabled) onOpenChange(next);
        }}
        label={label}
        height={sheetHeight}
        padding={0}
        finalFocusRef={pillRef}
      >
        <PanelContent popover={false}>
          {children({ stacked: true, onClose: () => onOpenChange(false) })}
        </PanelContent>
      </BottomSheet>
    </>
  );
}
