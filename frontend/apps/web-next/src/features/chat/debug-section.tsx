"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { Copy, Info } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, type ReactNode } from "react";
import { useCopy } from "@/lib/hooks/use-copy";

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

/**
 * A technical value (an id, a route) in a definition list, with a copy
 * button; a `hint` saying what the value is for sits behind an info button
 * beside the label, as a tooltip that opens on hover, focus or tap.
 */
export function CopyableValue({
  label,
  value,
  hint
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  const t = useTranslations();
  const { copy } = useCopy();
  return (
    <div className="min-w-0">
      <dt className="text-ax-text-secondary flex items-center gap-1 text-xs">
        {label}
        {hint ? (
          <Tooltip content={hint} touchTrigger="tap">
            <IconButton
              label={t("chat_debug_value_about", { label })}
              icon={<Info className="size-3.5" />}
              variant="ghost"
              size="sm"
            />
          </Tooltip>
        ) : null}
      </dt>
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
