import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/**
 * A space's security classification, wherever its content is used (decision
 * 19: the chat, the editors and the space itself): a shield and the class's
 * name, read as "Säkerhetsklass: Intern". `pill` stands on its own in a
 * header; `inline` sits in a line of supporting text (the chat's phone
 * header) and gives way first when the line is short. Nothing without a
 * classification. Server-component safe.
 *
 * @example <ClassificationToken name={space.security_classification?.name} />
 */
export function ClassificationToken({
  name,
  variant = "pill",
  className
}: {
  name?: string | null;
  variant?: "pill" | "inline";
  className?: string;
}) {
  const t = useTranslations();
  if (!name) return null;
  return (
    <span
      className={cn(
        variant === "pill"
          ? "bg-ax-muted text-ax-text-secondary inline-flex min-h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold"
          : "inline-flex min-w-0 items-center gap-1",
        className
      )}
    >
      <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
      <span className="sr-only">{t("security_classification_prefix")} </span>
      <span className={variant === "inline" ? "truncate" : undefined}>{name}</span>
    </span>
  );
}
