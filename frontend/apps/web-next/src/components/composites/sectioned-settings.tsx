"use client";

import type { LucideIcon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type SettingsSection = {
  id: string;
  label: string;
  icon: LucideIcon;
  node: ReactNode;
};

/**
 * One layout and one anchor navigation for long settings editors. All sections
 * stay visible, so native anchors fit here; Astryx TabList switches panels and
 * Outline would add a second sidebar inside the space sidebar.
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
      <header className="bg-background sticky top-0 z-30 border-b">
        <div className="mx-auto w-full max-w-4xl px-6">
          {header}
          <nav
            aria-label={navigationLabel}
            className="flex snap-x [scrollbar-width:none] gap-1 overflow-x-auto pb-2 [&::-webkit-scrollbar]:hidden"
          >
            {sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                aria-current={visibleActiveId === section.id ? "location" : undefined}
                onClick={() => setActiveId(section.id)}
                className={cn(
                  "focus-visible:outline-ring inline-flex min-h-9 snap-start items-center gap-1.5 rounded-md px-3 py-1.5 text-sm whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11",
                  visibleActiveId === section.id
                    ? "bg-muted text-foreground font-medium"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                )}
              >
                <section.icon aria-hidden="true" className="size-4 shrink-0" />
                {section.label}
              </a>
            ))}
          </nav>
        </div>
      </header>
      {/* Keep anchor targets and focused controls below the sticky header. */}
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-8 [&_*]:scroll-mt-48">
        {sections.map((section) => (
          <div key={section.id} id={section.id}>
            {section.node}
          </div>
        ))}
      </div>
    </div>
  );
}
