"use client";

import { ChevronRight, ExternalLink, type LucideIcon } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { Children, type ComponentProps, type ReactNode } from "react";

/**
 * A phone's index of rows under a group heading (decisions 21 and 22): an
 * editor's sections, Konto's settings. The rows run edge to edge; their text
 * keeps to the page's gutter, `--index-inset` (16 px unless the page sets it).
 */
export function IndexGroup({ title, children }: { title?: string; children: ReactNode }) {
  // A group whose rows all depend on what the user may do can be empty.
  if (Children.toArray(children).length === 0) return null;
  return (
    <div className="flex flex-col">
      {title ? (
        <h2 className="text-ax-text-secondary px-[var(--index-inset,1rem)] pb-1.5 text-[0.8125rem] font-semibold">
          {title}
        </h2>
      ) : null}
      <ul className="border-ax-border divide-ax-border divide-y border-y">{children}</ul>
    </div>
  );
}

/**
 * One row of an index: a link with what it holds now at its end (read once, as
 * part of its name) and a chevron. An external one opens in a new tab and
 * says so, with the external-link icon in place of the chevron.
 */
export function IndexRow({
  icon: Icon,
  label,
  summary,
  isExternal = false,
  ...link
}: Omit<ComponentProps<typeof Link>, "children" | "className"> & {
  icon?: LucideIcon;
  label: ReactNode;
  summary?: ReactNode;
  isExternal?: boolean;
}) {
  const t = useTranslations();
  return (
    <li>
      <Link
        {...link}
        {...(isExternal ? { target: "_blank", rel: "noopener noreferrer" } : {})}
        className="hover:bg-ax-hover active:bg-ax-pressed focus-visible:outline-ring flex min-h-14 items-center gap-3 px-[var(--index-inset,1rem)] py-2 focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        {Icon ? (
          <Icon aria-hidden="true" className="text-ax-text-secondary size-5 shrink-0" />
        ) : null}
        <span className="min-w-0 flex-1 break-words">
          {label}
          {isExternal ? <span className="sr-only"> {t("chat_opens_in_new_tab")}</span> : null}
        </span>
        {summary ? (
          <>
            <span className="sr-only">, </span>
            <span className="text-ax-text-secondary max-w-[45%] truncate text-sm">{summary}</span>
          </>
        ) : null}
        {isExternal ? (
          <ExternalLink aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
        ) : (
          <ChevronRight aria-hidden="true" className="text-ax-text-secondary size-4 shrink-0" />
        )}
      </Link>
    </li>
  );
}
