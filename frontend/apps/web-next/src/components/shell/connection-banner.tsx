"use client";

import { useTranslations } from "next-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { useOnline } from "@/lib/hooks/use-online";
import { cn } from "@/lib/utils";

/**
 * Tells the user, under the screen's header, that the browser is offline and
 * what that means: questions are not sent and changes are not saved until it
 * is back. The shell shows it at the top of the page; a page with its own
 * header (the chat's, a PageBar) shows it under that header, and the shell's
 * gives way in CSS (app-shell.tsx). A lasting state, so not an alert:
 * `ConnectionAnnouncer` says the change once. Its own store subscription,
 * never a context above the page.
 */
export function ConnectionBanner({ className }: { className?: string }) {
  const t = useTranslations();
  if (!useOnline()) {
    return (
      <QuietBanner
        status="warning"
        title={t("offline_banner_title")}
        description={t("offline_banner_description")}
        collapsible={false}
        className={cn("m-3 lg:m-4", className)}
      />
    );
  }
  return null;
}

/** Says once, politely, that the connection was lost or is back. Rendered once, by the shell. */
export function ConnectionAnnouncer() {
  const t = useTranslations();
  useAnnounceChange(useOnline() ? t("offline_restored") : t("offline_banner_title"));
  return null;
}
