"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { useCollator } from "@astryxdesign/core/i18n";
import { Check, ChevronDown } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { useSpace } from "@/features/spaces/use-space";
import Link from "@/lib/link";
import { cn } from "@/lib/utils";
import { spaceApps } from "./apps";

/** Same-space app links; the title remains the page's textual heading. */
export function AppSwitcher({ appId }: { appId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const collator = useCollator();
  const apps = spaceApps(space, collator.compare);
  const [open, setOpen] = useState(false);
  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      label={t("select_an_app")}
      closeButtonLabel={t("close")}
      width="24rem"
      content={
        <nav aria-label={t("select_an_app")} className="max-h-80 overflow-y-auto p-2">
          {apps.length === 0 && (
            <p className="text-ax-text-secondary p-3 text-sm">{t("no_results")}</p>
          )}
          <ul className="flex flex-col gap-1">
            {apps.map((app) => (
              <li key={app.id}>
                <Link
                  href={`/spaces/${routeId}/apps/${app.id}`}
                  aria-current={app.id === appId ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "text-ax-text hover:bg-ax-hover focus-visible:outline-ring rounded-ax-element flex min-h-11 items-center justify-between gap-3 px-3 py-2 text-sm break-words focus-visible:outline-2 focus-visible:outline-offset-2",
                    app.id === appId && "bg-ax-accent-muted text-ax-text-accent"
                  )}
                >
                  <span className="min-w-0">{app.name}</span>
                  {app.id === appId && <Check className="size-4 shrink-0" />}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      }
    >
      <IconButton
        label={t("select_an_app")}
        tooltip={t("select_an_app")}
        icon={<ChevronDown className="size-4" />}
        variant="ghost"
        className="shrink-0 pointer-coarse:size-11"
      />
    </Popover>
  );
}
