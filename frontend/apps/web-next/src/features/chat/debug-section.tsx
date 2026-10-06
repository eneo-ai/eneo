"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useClipboard } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";

/**
 * One disclosure section of the Felsök tab: a heading with an optional count,
 * open by default when it has something to show.
 */
export function DebugSection({
  title,
  count = null,
  defaultOpen = true,
  children
}: {
  title: string;
  count?: number | null;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="border-ax-border border-b">
      <Collapsible
        trigger={
          <span className="flex min-w-0 items-center gap-2">
            <h3 id={headingId} className="min-w-0 flex-1 truncate text-sm font-semibold">
              {title}
            </h3>
            {count !== null && (
              <span className="bg-ax-muted text-ax-text-secondary rounded-full px-1.5 text-[11px] font-bold tabular-nums">
                {count}
              </span>
            )}
          </span>
        }
        defaultIsOpen={defaultOpen}
      >
        <div className="flex flex-col gap-3 pb-4">{children}</div>
      </Collapsible>
    </section>
  );
}

/** A technical value (an id, a route) in a definition list, with a copy button. */
export function CopyableValue({ label, value }: { label: string; value: string }) {
  const t = useTranslations();
  const { copy } = useClipboard({ announce: t("copied_to_clipboard") });
  return (
    <div className="min-w-0">
      <dt className="text-ax-text-secondary text-xs">{label}</dt>
      <dd className="mt-0.5 flex min-w-0 items-center gap-1">
        <code
          className="min-w-0 flex-1 truncate font-mono text-sm leading-5 font-medium"
          title={value}
        >
          {value}
        </code>
        <IconButton
          label={t("chat_debug_copy_value", { label })}
          icon={<Copy className="size-3.5" />}
          variant="ghost"
          size="sm"
          onClick={() => void copy(value)}
        />
      </dd>
    </div>
  );
}
