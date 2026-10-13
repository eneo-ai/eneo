"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Why there is no create button: shown as text, not hidden in a tooltip, so
 * everyone can read it (and it works with the keyboard and on touch).
 */
export function NoCreatePermissionInfo({ resourceType }: { resourceType: string }) {
  const t = useTranslations();

  return (
    <p className="text-ax-text-secondary flex max-w-md items-start gap-1.5 text-sm">
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{t("knowledge_create_no_permission", { resourceType })}</span>
    </p>
  );
}
