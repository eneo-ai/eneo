"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

export type SettingsSection = {
  id: string;
  label: string;
  icon: LucideIcon;
  node: ReactNode;
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
 */
export function SectionedSettings({
  header,
  navigationLabel,
  sections
}: {
  header: ReactNode;
  navigationLabel: string;
  sections: readonly SettingsSection[];
}) {
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

  return (
    <div data-space-full-bleed className="flex shrink-0 flex-col">
      <header className="bg-ax-surface border-ax-border sticky top-0 z-30 border-b">
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
      {/* Keep anchor targets and focused controls below the sticky header. */}
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8 [&_*]:scroll-mt-40">
        {sections.map((section) => (
          <div key={section.id} id={section.id}>
            {section.node}
          </div>
        ))}
      </div>
    </div>
  );
}
