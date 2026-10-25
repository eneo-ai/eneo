"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import type { LucideIcon } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode
} from "react";
import { PageBar } from "@/components/shell/page-bar";
import { PHONE_QUERY } from "@/lib/hooks/use-media-match";
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
  /** On a phone's index: the heading the section is listed under. */
  group?: string;
};

/** What a phone's settings index needs (decision 21): its page bar. */
export type SettingsPhoneIndex = {
  /** The list the resource sits in: where the index's back link goes. */
  parent: { label: string; href: string };
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
   * the tablet's page, as space settings does.
   */
  phone?: SettingsPhoneIndex;
};

/**
 * One layout and one anchor navigation for long settings editors: a sticky
 * header with the title block, then the sections as an Astryx TabList in its
 * navigation pattern (a named `<nav>` of anchor links, the section in view
 * marked current). All sections stay visible, so the links are native
 * anchors, not a `role="tablist"`. A strip narrower than its links scrolls
 * with edge fades and keeps the current link in view; arrow keys move
 * through it, so no label is ever truncated. The editor owns the page
 * surface (`data-space-full-bleed`): the space frame drops its inset and,
 * on editor routes, its header, so the sticky header is the only chrome.
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
const OPENED_FROM_INDEX = "settingsSectionFromIndex";

const openedFromIndex = () => window.history.state?.[OPENED_FROM_INDEX] === true;

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
 * The address is read on arrival; after that the view changes by these
 * controls and by the system's back and forward.
 */
function usePhoneView(ids: readonly string[], openFirst: string | undefined) {
  const pathname = usePathname();
  const requested = useSearchParams()?.get("section") ?? null;
  const valid = (id: string | null) => (id !== null && ids.includes(id) ? id : null);
  const [chosen, setChosen] = useState(() => valid(requested) ?? valid(openFirst ?? null));
  // A section gone since (a permission changed) shows the index, and is
  // forgotten, so it does not come back by itself (adjusted during render).
  if (chosen !== null && valid(chosen) === null) setChosen(null);
  const view = valid(chosen);
  const focusNext = useRef<FocusNext>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  // The view in the last commit, and the address it stands for: the system's
  // back and forward compare against them.
  const shownRef = useRef(view);
  const addressRef = useRef<string | null>(null);
  useEffect(() => {
    shownRef.current = view;
  });

  const href = (id: string | null) => (id ? `${pathname}?section=${id}` : pathname);

  // The system back and forward move between the index and a section: follow
  // the address they land on, focus included. A move that only changes the
  // hash (a skip link, a link to a field) is not one. (Next applies history
  // changes to its search params after the fact, so those could still name a
  // section just left.)
  useEffect(() => {
    addressRef.current = window.location.pathname + window.location.search;
    const follow = () => {
      const address = window.location.pathname + window.location.search;
      if (address === addressRef.current) return;
      addressRef.current = address;
      const section = new URLSearchParams(window.location.search).get("section");
      const left = shownRef.current;
      focusNext.current = section ? { section } : left ? { row: left } : null;
      setChosen(section);
    };
    window.addEventListener("popstate", follow);
    return () => window.removeEventListener("popstate", follow);
  }, []);

  const go = (method: "pushState" | "replaceState", id: string | null, fromIndex: boolean) => {
    window.history[method](fromIndex ? { [OPENED_FROM_INDEX]: true } : null, "", href(id));
    addressRef.current = window.location.pathname + window.location.search;
  };

  const open = (id: string, focus?: HTMLElement | null) => {
    // From a section, another one replaces it: Back still leads to the index.
    if (view === null) go("pushState", id, true);
    else go("replaceState", id, openedFromIndex());
    focusNext.current = focus ? { element: focus } : { section: id };
    setChosen(id);
  };

  const back = () => {
    if (openedFromIndex()) window.history.back();
    else go("replaceState", null, false);
    focusNext.current = view ? { row: view } : null;
    setChosen(null);
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

  // Turned across 768 px, CSS hides what the other layout showed: a tablet's
  // strip and the sections a phone does not show, or a phone's index and bar.
  // Focus that was there goes somewhere logical (ACCESSIBILITY.md): a field
  // in a section the phone does not show opens that section, the field kept;
  // an index row goes to its section's heading; anything else to the section
  // in view, else to the index row or the first section.
  useEffect(() => {
    const list = window.matchMedia(PHONE_QUERY);
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
          window.history.replaceState(null, "", `${window.location.pathname}?section=${section}`);
          addressRef.current = window.location.pathname + window.location.search;
          focusNext.current = { element };
          setChosen(section);
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

  // A view opened from a control takes focus to what it shows: a section to
  // its heading, the index to the row it was opened from. Not on arrival: a
  // resource just created focuses its name field itself.
  useLayoutEffect(() => {
    const next = focusNext.current;
    focusNext.current = null;
    if (next && rootRef.current) focusIn(rootRef.current, next);
  }, [view]);

  return { view, href, open, back, reveal, rootRef };
}

function SettingsLayout({
  header,
  navigationLabel,
  sections,
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

  const view = views?.view ?? null;
  const shown = sections.find((section) => section.id === view);

  // A save error's link names its field; on a phone the field may sit in a
  // section out of view, so the link opens that section first, and either
  // way focuses the field in place rather than adding a history entry.
  const openFailedField = (event: MouseEvent) => {
    if (!views || !window.matchMedia(PHONE_QUERY).matches) return;
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
              until="md"
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
          ) : (
            <PageBar
              until="md"
              parent={views.phone.parent}
              title={views.phone.title}
              isTitleShown
              // A filled button needs more room from the edge than the bar's ghost back link.
              actions={
                views.phone.actions ? <span className="pe-2.5">{views.phone.actions}</span> : null
              }
            />
          )}
          {/* The header is the tablet's. A phone shows the name in the bar,
              the h1 for assistive technology, and the save state: here on
              the index, in the bar on a section, where it stays in view. */}
          <h1 className="sr-only md:hidden">{views.phone.title}</h1>
          <div
            data-editor-strip
            className={cn("flex min-h-11 items-center px-4 pt-2 md:hidden", shown && "hidden")}
          >
            <SaveStatusIndicator isQuiet />
          </div>
        </>
      ) : null}
      {/* Under a space's page bar on a phone (it sticks there too); main's
          scroll padding for the bar adds to the anchors' scroll margin. */}
      <header
        className={cn(
          "bg-ax-surface border-ax-border sticky top-0 z-30 border-b max-md:group-has-[[data-phone-page-bar]]/shell:top-14",
          views && "max-md:hidden"
        )}
      >
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-1 px-6">
          {header}
          <TabList
            value={visibleActiveId}
            onChange={setActiveId}
            overflow="scroll"
            aria-label={navigationLabel}
            className="-mb-px"
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
          className={cn("md:hidden", shown && "hidden")}
        />
      ) : null}
      {/* Keep anchor targets and focused controls below the sticky header. */}
      <div
        className={cn(
          "mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8 [&_*]:scroll-mt-40",
          views && "max-md:px-4 max-md:py-4 max-md:[&_*]:scroll-mt-4",
          views && !shown && "max-md:hidden"
        )}
      >
        {sections.map((section) => (
          <div
            key={section.id}
            id={section.id}
            data-editor-section={views ? section.id : undefined}
            data-current={views && section === shown ? "" : undefined}
            className={cn(views && section !== shown && "max-md:hidden")}
          >
            {section.node}
          </div>
        ))}
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
  const groups: { label?: string; sections: SettingsSection[] }[] = [];
  for (const section of sections) {
    const last = groups.at(-1);
    if (last && last.label === section.group) last.sections.push(section);
    else groups.push({ label: section.group, sections: [section] });
  }

  return (
    <nav
      data-editor-index
      aria-label={label}
      className={cn("flex flex-col gap-6 pt-2 pb-8", className)}
    >
      {groups.map((group, index) => (
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
