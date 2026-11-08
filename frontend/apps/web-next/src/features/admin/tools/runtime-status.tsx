import { Skeleton } from "@astryxdesign/core/Skeleton";
import type { ReactNode } from "react";
import { useTranslations } from "use-intl";
import { cn } from "@/lib/utils";
import { runtimeMessageKeys, type RuntimeStatus } from "./bundled";

const CARD = "border-ax-border rounded-ax-container border p-5";

/**
 * The place of the runtime status above the tabs, held from the first paint:
 * the status waits for the backend's probe of the runtime (up to three
 * seconds), and a card that arrived later pushed the tabs and the list down.
 * It holds the common card, title, state and versions (146 px on a phone,
 * where the state takes two lines; 125 px from 600 px wide), and the other
 * states fill it. A warning adds lines and grows it: what the operator must
 * do is not cut, and a healthy runtime has none.
 */
export function RuntimeStatusArea({ children }: { children: ReactNode }) {
  return (
    <div data-slot="runtime-status" className="flex min-h-37 flex-col sm:min-h-32">
      {children}
    </div>
  );
}

/** Where the runtime status will be, while it is read (decorative, like the page around it). */
export function RuntimeStatusPlaceholder() {
  return (
    <div aria-hidden="true" className={cn(CARD, "flex grow flex-col gap-3")}>
      <Skeleton height={16} width="40%" radius={1} />
      <Skeleton index={1} height={12} width="90%" radius={1} />
      <Skeleton index={2} height={12} width="30%" radius={1} />
    </div>
  );
}

/** The state of the tool runtime shipped with Eneo, as the backend last saw it. */
export function RuntimeStatusCard({ status }: { status: RuntimeStatus | null | undefined }) {
  const t = useTranslations();
  if (!status) return null;
  return (
    // grow: fills its place in RuntimeStatusArea when a state has fewer lines.
    <section aria-labelledby="runtime-status-title" className={cn(CARD, "grow")}>
      <h2 id="runtime-status-title" className="font-semibold">
        {t("tools_runtime_title")}
      </h2>
      <div className="text-ax-text-secondary mt-2 flex flex-col gap-2 text-sm">
        {runtimeMessageKeys(status).map((key) => (
          <p key={key}>{t(key)}</p>
        ))}
        {status.version && (
          <p>
            {t("tools_runtime_versions", {
              backend: status.expected_version,
              runtime: status.version
            })}
          </p>
        )}
      </div>
    </section>
  );
}
