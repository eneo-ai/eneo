import { SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import type { LucideIcon } from "lucide-react";
import {
  pushUrl,
  readUrlState,
  replaceUrl,
  usePathname,
  useRouter,
  useSearchParams
} from "@/lib/navigation";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode
} from "react";
import { NAV_ITEM_CLASSES } from "@/components/shell/nav-styles";
import { PageBar } from "@/components/shell/page-bar";
import { MEDIA } from "@/lib/breakpoints";
import { PHONE_SCREEN_QUERY } from "@/lib/hooks/use-media-match";
import { cn } from "@/lib/utils";
import { IndexGroup, IndexRow } from "./index-rows";
import { inPlaceLink } from "./in-place-link";
import { SaveStatusIndicator } from "./save-status";

export type SettingsSection = {
  id: string;
  label: string;
  icon: LucideIcon;
  node: ReactNode;
  /** On a phone's index: what the section holds now, in a few words ("3 källor"). */
  summary?: string;
  /** On a phone's index and in the list beside the form: the heading the section is listed under. */
  group?: string;
};

/** What a phone's settings index needs (decision 21): its page bar. */
export type SettingsPhoneIndex = {
  /**
   * The list the resource sits in: where the index's back link goes. Without it the index has no
   * page bar of its own, for a page whose frame already supplies one (a space's settings).
   */
  parent?: { label: string; href: string };
  /** The resource's name: the bar's title, and the page's h1 on a phone. */
  title: string;
  /** The index bar's actions ("Testa"). */
  actions?: ReactNode;
  /** Open on this section instead of the index: a resource just created opens General. */
  openFirst?: string;
};

type SectionedSettingsProps = {
  header: ReactNode;
  navigationLabel: string;
  sections: readonly SettingsSection[];
  /**
   * Below 768 px, open on an index of the sections, each a view of its own
   * with a page bar back to the index (decision 21). Without it a phone shows
   * the tablet's page.
   */
  phone?: SettingsPhoneIndex;
  /**
   * A frame's header sits above (a space's settings): the editor starts on the line of the
   * header's content, the pages' shared column, instead of centring.
   */
  isFramed?: boolean;
};

/**
 * One layout and one anchor navigation for long settings editors: a sticky
 * header with the title block, then the sections as an Astryx TabList in its
 * navigation pattern (a named `<nav>` of anchor links, the section in view
 * marked current). All sections stay visible, so the links are native
 * anchors, not a `role="tablist"`. A strip narrower than its links scrolls
 * with edge fades and keeps the current link in view; arrow keys move
 * through it, so no label is ever truncated. From 1024 px the links leave
 * the header for a list beside the form, under the sections' groups, that
 * stays in view while the form scrolls: every section is named at once. The
 * header's height is measured, so anchors land below it at either size. The
 * editor owns the page surface (`data-space-full-bleed`): the space frame
 * drops its inset and, on editor routes, its header, so the sticky header is
 * the only chrome.
 *
 * With `phone`, a phone shows an index of the sections instead, and one
 * section at a time. The index and the sections are views of one mounted
 * tree: CSS shows the one in view, so what was typed in a section, and its
 * pending save, outlive a trip to the index or a turn to the tablet layout.
 */
export function SectionedSettings({ phone, ...props }: SectionedSettingsProps) {
  return phone ? <WithPhoneIndex {...props} phone={phone} /> : <SettingsLayout {...props} />;
}

type PhoneViews = {
  phone: SettingsPhoneIndex;
  /** The section in view, or null for the index. */
  view: string | null;
  href: (id: string | null) => string;
  open: (id: string, focus?: HTMLElement | null) => void;
  back: () => void;
  reveal: (element: HTMLElement) => void;
  rootRef: React.RefObject<HTMLDivElement | null>;
};

function WithPhoneIndex({
  phone,
  ...props
}: Omit<SectionedSettingsProps, "phone"> & { phone: SettingsPhoneIndex }) {
  const views = usePhoneView(
    props.sections.map((section) => section.id),
    phone.openFirst
  );
  return <SettingsLayout {...props} views={{ ...views, phone }} />;
}

/** Where focus goes once a view has changed. */
type FocusNext = { section: string } | { row: string } | { element: HTMLElement } | null;

/**
 * Marks the history entry a section was opened into from the index, so Back
 * pops it rather than adding one. Kept in the entry itself (Next keeps it
 * beside its own state), so a reload or the system's forward still knows.
 */
const openedFromIndex = () => readUrlState().settingsSectionFromIndex === true;

/**
 * Focus what a view shows: an element in it if it takes focus, else its
 * section's heading (made focusable for this), else the section itself.
 */
function focusIn(root: HTMLElement, next: Exclude<FocusNext, null>) {
  if ("row" in next) {
    root.querySelector<HTMLElement>(`[data-editor-row="${next.row}"]`)?.focus();
    return;
  }
  if ("element" in next && next.element.tabIndex >= 0) {
    next.element.focus();
    return;
  }
  const section =
    "element" in next
      ? next.element.closest<HTMLElement>("[data-editor-section]")
      : root.querySelector<HTMLElement>(`[data-editor-section="${next.section}"]`);
  const heading = section?.querySelector<HTMLElement>("h2, h3") ?? section;
  if (heading && heading.tabIndex < 0) heading.setAttribute("tabindex", "-1");
  heading?.focus();
}

/**
 * Which view a phone shows: the index (null) or one section. The address
 * keeps it (`?section=`), so a reload or a shared link opens the same view,
 * and opening a section from the index pushes an entry the system back pops.
 * Every committed address chooses the view, including browser Back/Forward
 * and other links to this same route.
 */
function usePhoneView(ids: readonly string[], openFirst: string | undefined) {
  const pathname = usePathname();
  const router = useRouter();
  const requested = useSearchParams().get("section");
  const valid = (id: string | null) => (id !== null && ids.includes(id) ? id : null);
  // Creation keeps its fields visible for mount-focus while the URL catches up.
  // Subsequent views belong to the URL.
  const [initialSection, setInitialSection] = useState(() =>
    requested === null ? valid(openFirst ?? null) : null
  );
  if (initialSection !== null && requested !== null) setInitialSection(null);
  const view = valid(requested ?? initialSection);
  const focusNext = useRef<FocusNext>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const shownRef = useRef(view);

  useLayoutEffect(() => {
    if (initialSection)
      replaceUrl(`?section=${encodeURIComponent(initialSection)}`, {
        state: { settingsSectionFromIndex: false }
      });
  }, [initialSection]);

  // Forget a removed or invalid section so restoring permissions does not reopen it.
  useEffect(() => {
    if (requested !== null && view === null) {
      replaceUrl(pathname, { state: { settingsSectionFromIndex: false } });
    }
  }, [requested, view, pathname]);

  const href = (id: string | null) =>
    id ? `${pathname}?section=${encodeURIComponent(id)}` : pathname;
  const go = (replace: boolean, id: string | null, fromIndex: boolean) => {
    (replace ? replaceUrl : pushUrl)(href(id), { state: { settingsSectionFromIndex: fromIndex } });
  };
  // For the listeners below, which outlive a render.
  const goRef = useRef(go);
  useEffect(() => {
    goRef.current = go;
  });

  const open = (id: string, focus?: HTMLElement | null) => {
    focusNext.current = focus ? { element: focus } : { section: id };
    // From a section, another one replaces it: Back still leads to the index.
    go(view !== null, id, view === null || openedFromIndex());
  };

  const back = () => {
    focusNext.current = view ? { row: view } : null;
    if (openedFromIndex()) router.back();
    else go(true, null, false);
  };

  /** Focus an element in the section in view, without a history entry. */
  const reveal = (element: HTMLElement) => {
    if (rootRef.current) focusIn(rootRef.current, { element });
  };

  // The editor's control that had focus last (focusin: an element that CSS
  // hides fires nothing on its way out).
  const lastFocus = useRef<HTMLElement | null>(null);
  const idsRef = useRef(ids);
  useEffect(() => {
    idsRef.current = ids;
  });
  useEffect(() => {
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target;
      lastFocus.current =
        target instanceof HTMLElement && rootRef.current?.contains(target) ? target : null;
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);

  // Turned between a phone's layout and a tablet's, CSS hides what the other
  // layout showed: a tablet's strip and the sections a phone does not show, or
  // a phone's index and bar.
  // Focus that was there goes somewhere logical (ACCESSIBILITY.md): a field
  // in a section the phone does not show opens that section, the field kept;
  // an index row goes to its section's heading; anything else to the section
  // in view, else to the index row or the first section.
  useEffect(() => {
    const list = window.matchMedia(PHONE_SCREEN_QUERY);
    const turned = () => {
      const element = lastFocus.current;
      const root = rootRef.current;
      if (!element || !root) return;
      const active = document.activeElement;
      if (active !== element && active !== document.body) return;
      if (active === element && element.getClientRects().length > 0) return;
      const inView = shownRef.current;
      const section = element.closest<HTMLElement>("[data-editor-section]")?.dataset.editorSection;
      if (list.matches) {
        if (section && section !== inView) {
          // The entry stays what it was: one opened from the index keeps its
          // marker, so Back still pops it and Forward brings it back.
          focusNext.current = { element };
          goRef.current(true, section, openedFromIndex());
          return;
        }
        // The tablet's strip names the section it marks.
        const tab = element.closest("a[href^='#']")?.getAttribute("href")?.slice(1);
        focusIn(
          root,
          inView
            ? { section: inView }
            : { row: tab && idsRef.current.includes(tab) ? tab : (idsRef.current[0] ?? "") }
        );
        return;
      }
      const row = element.closest<HTMLElement>("[data-editor-row]")?.dataset.editorRow;
      const target = row ?? inView ?? idsRef.current[0];
      if (target) focusIn(root, { section: target });
    };
    list.addEventListener("change", turned);
    return () => list.removeEventListener("change", turned);
  }, []);

  // Across 1024 px the section links move between the header's strip and the
  // list beside the form: a link that had focus hands it to its twin.
  useEffect(() => {
    const list = window.matchMedia(MEDIA.lg);
    const turned = () => {
      const element = lastFocus.current;
      const root = rootRef.current;
      const href = element?.closest("a[href^='#']")?.getAttribute("href");
      const active = document.activeElement;
      if (!element || !root || !href || (active !== element && active !== document.body)) return;
      if (element.getClientRects().length > 0) return;
      [...root.querySelectorAll<HTMLElement>("a[href^='#']")]
        .find(
          (link) =>
            link !== element &&
            link.getAttribute("href") === href &&
            link.getClientRects().length > 0
        )
        ?.focus();
    };
    list.addEventListener("change", turned);
    return () => list.removeEventListener("change", turned);
  }, []);

  // A view opened from a control takes focus to what it shows: a section to
  // its heading, the index to the row it was opened from. Not on arrival: a
  // resource just created focuses its name field itself.
  useLayoutEffect(() => {
    const previous = shownRef.current;
    shownRef.current = view;
    if (previous === view) return;
    const next =
      focusNext.current ?? (view ? { section: view } : previous ? { row: previous } : null);
    focusNext.current = null;
    if (next && rootRef.current) focusIn(rootRef.current, next);
  }, [view]);

  return { view, href, open, back, reveal, rootRef };
}

function SettingsLayout({
  header,
  navigationLabel,
  sections,
  isFramed = false,
  views
}: Omit<SectionedSettingsProps, "phone"> & { views?: PhoneViews }) {
  const [activeId, setActiveId] = useState(sections[0]?.id ?? "");
  const sectionIds = sections.map((section) => section.id).join(",");
  const visibleActiveId = sections.some((section) => section.id === activeId)
    ? activeId
    : (sections[0]?.id ?? "");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { rootMargin: "-128px 0px -55% 0px" }
    );
    for (const id of sectionIds.split(",")) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [sectionIds]);

  // The header's height, for the anchors' scroll margin and the list's sticky
  // offset: taller with the strip below 1024 px than without it. A phone hides
  // the header (no size): the last height stays.
  const headerRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const element = headerRef.current;
    const root = element?.parentElement;
    if (!element || !root || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const height = Math.ceil(entry?.borderBoxSize?.[0]?.blockSize ?? 0);
      if (height > 0) root.style.setProperty("--editor-header-h", `${height}px`);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Centred on its own page; under a frame's header, the pages' column (72rem) with this
  // layout's own px-6 on each side, so its text starts on the header's line.
  const width = isFramed ? "mx-auto max-w-[75rem]" : "mx-auto max-w-4xl lg:max-w-[74rem]";

  const view = views?.view ?? null;
  const shown = sections.find((section) => section.id === view);

  // A save error's link names its field; on a phone the field may sit in a
  // section out of view, so the link opens that section first, and either
  // way focuses the field in place rather than adding a history entry.
  const openFailedField = (event: MouseEvent) => {
    if (!views || !window.matchMedia(PHONE_SCREEN_QUERY).matches) return;
    const link = (event.target as Element).closest?.('a[href^="#"]');
    const field = link ? document.getElementById(link.getAttribute("href")!.slice(1)) : null;
    const section = field?.closest<HTMLElement>("[data-editor-section]")?.dataset.editorSection;
    if (!field || !section) return;
    event.preventDefault();
    if (section === view) views.reveal(field);
    else views.open(section, field);
  };

  return (
    <div
      ref={views?.rootRef}
      data-space-full-bleed
      data-editor-view={views ? (shown ? "section" : "index") : undefined}
      onClickCapture={views ? openFailedField : undefined}
      className="flex shrink-0 flex-col"
    >
      {views ? (
        <>
          {shown ? (
            <PageBar
              until="phone"
              parent={{
                label: views.phone.title,
                ...inPlaceLink(views.href(null), views.back)
              }}
              title={shown.label}
              isTitleShown
              actions={
                <span className="pe-2.5">
                  <SaveStatusIndicator isQuiet isCompact />
                </span>
              }
            />
          ) : views.phone.parent ? (
            <PageBar
              until="phone"
              parent={views.phone.parent}
              title={views.phone.title}
              isTitleShown
              // A filled button needs more room from the edge than the bar's ghost back link.
              actions={
                views.phone.actions ? <span className="pe-2.5">{views.phone.actions}</span> : null
              }
            />
          ) : null}
          {/* The header is the tablet's. A phone shows the name in the bar,
              the h1 for assistive technology, and the save state: here on
              the index, in the bar on a section, where it stays in view. */}
          {views.phone.parent ? (
            <h1 className="wide:hidden sr-only">{views.phone.title}</h1>
          ) : shown ? null : (
            // The page's frame has the h1 (the space) and a bar whose title shows only once
            // the page has scrolled: the index names itself.
            <h2 className="text-ax-text wide:hidden m-0 px-4 pt-4 text-2xl leading-tight font-semibold">
              {views.phone.title}
            </h2>
          )}
          <div
            data-editor-strip
            className={cn("wide:hidden flex min-h-11 items-center px-4 pt-2", shown && "hidden")}
          >
            <SaveStatusIndicator isQuiet />
          </div>
        </>
      ) : null}
      {/* Under a space's page bar on a phone (it sticks there too); main's
          scroll padding for the bar adds to the anchors' scroll margin. */}
      <header
        ref={headerRef}
        className={cn(
          "bg-ax-surface border-ax-border phone:group-has-[[data-phone-page-bar]]/shell:top-14 sticky top-0 z-30 border-b",
          views && "phone:hidden"
        )}
      >
        <div className={cn("flex w-full flex-col gap-1 px-6", width)}>
          {header}
          <TabList
            value={visibleActiveId}
            onChange={setActiveId}
            overflow="scroll"
            aria-label={navigationLabel}
            className="-mb-px lg:hidden"
          >
            {sections.map((section) => (
              <Tab
                key={section.id}
                value={section.id}
                href={`#${section.id}`}
                label={section.label}
                icon={<section.icon aria-hidden="true" className="size-4" />}
              />
            ))}
          </TabList>
        </div>
      </header>
      {views ? (
        <PhoneIndex
          label={navigationLabel}
          sections={sections}
          href={views.href}
          open={views.open}
          className={cn("wide:hidden", shown && "hidden")}
        />
      ) : null}
      {/* Keep anchor targets and focused controls below the sticky header. */}
      <div
        className={cn(
          "flex w-full flex-col px-6 py-8 lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:items-start lg:gap-x-8 [&_*]:scroll-mt-[calc(var(--editor-header-h,9.5rem)+0.5rem)]",
          width,
          views && "phone:px-4 phone:py-4 phone:[&_*]:scroll-mt-4",
          views && !shown && "phone:hidden"
        )}
      >
        {/* Its top includes the content's padding: the gap above it stays the same once it sticks.
            A short window scrolls it on its own; its padding keeps the focus ring inside that
            scroll box, and the side margins keep the items on the line. */}
        <nav
          data-editor-rail
          aria-label={navigationLabel}
          className="sticky top-[calc(var(--editor-header-h,9.5rem)+2rem)] -mx-1 flex max-h-[calc(100svh-var(--editor-header-h,9.5rem)-5rem)] flex-col gap-2 overflow-y-auto p-1 max-lg:hidden"
        >
          {groupSections(sections).map((group, index) => {
            const items = group.sections.map((section) => (
              <SideNavItem
                key={section.id}
                label={section.label}
                icon={section.icon}
                href={`#${section.id}`}
                isSelected={section.id === visibleActiveId}
                onClick={() => setActiveId(section.id)}
              />
            ));
            return group.label ? (
              <SideNavSection key={group.label} title={group.label} className={NAV_ITEM_CLASSES}>
                {items}
              </SideNavSection>
            ) : (
              <div key={index} className={NAV_ITEM_CLASSES}>
                {items}
              </div>
            );
          })}
        </nav>
        <div className="flex max-w-4xl min-w-0 flex-col gap-8">
          {sections.map((section) => (
            <div
              key={section.id}
              id={section.id}
              data-editor-section={views ? section.id : undefined}
              data-current={views && section === shown ? "" : undefined}
              className={cn(views && section !== shown && "phone:hidden")}
            >
              {section.node}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * A phone's index: the sections as rows under their group headings, each a
 * link to its own view with what it holds now at the end (read once, as part
 * of the row's name), in the editor's own order.
 */
function PhoneIndex({
  label,
  sections,
  href,
  open,
  className
}: {
  label: string;
  sections: readonly SettingsSection[];
  href: (id: string) => string;
  open: (id: string) => void;
  className?: string;
}) {
  return (
    <nav
      data-editor-index
      aria-label={label}
      className={cn("flex flex-col gap-6 pt-2 pb-8", className)}
    >
      {groupSections(sections).map((group, index) => (
        <IndexGroup key={group.label ?? index} title={group.label}>
          {group.sections.map((section) => (
            <IndexRow
              key={section.id}
              {...inPlaceLink(href(section.id), () => open(section.id))}
              prefetch={false}
              data-editor-row={section.id}
              icon={section.icon}
              label={section.label}
              summary={section.summary}
            />
          ))}
        </IndexGroup>
      ))}
    </nav>
  );
}

/** Runs of sections that share a group, in the editor's order; an ungrouped run has no label. */
function groupSections(sections: readonly SettingsSection[]) {
  const groups: { label?: string; sections: SettingsSection[] }[] = [];
  for (const section of sections) {
    const last = groups.at(-1);
    if (last && last.label === section.group) last.sections.push(section);
    else groups.push({ label: section.group, sections: [section] });
  }
  return groups;
}
