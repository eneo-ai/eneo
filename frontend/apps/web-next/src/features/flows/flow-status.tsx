"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { useTranslations } from "next-intl";

/** "Publicerad, version 3" or "Utkast": the text carries the state, the colour repeats it. */
export function FlowStatusBadge({ publishedVersion }: { publishedVersion?: number | null }) {
  const t = useTranslations();
  return publishedVersion != null ? (
    <Badge variant="success" label={t("flows_status_published", { version: publishedVersion })} />
  ) : (
    <Badge variant="neutral" label={t("flows_status_draft")} />
  );
}
