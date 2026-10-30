"use client";
import { useTranslations } from "next-intl";
import type { Schema } from "@/lib/api/models";

export function SkillDependencies({
  dependencies
}: {
  dependencies: Schema<"SkillBindingSummary">["dependencies"];
}) {
  const t = useTranslations();
  if (!dependencies?.length) return null;
  return (
    <details className="text-ax-text-secondary mt-2 text-xs">
      <summary className="cursor-pointer">
        {t("skills_reference_dependencies")} ({dependencies.length})
      </summary>
      <ul className="mt-2 flex flex-col gap-1">
        {dependencies.map((item) => (
          <li key={item.skill_id} className="break-words">
            {item.display_name} ·{" "}
            {t("skills_revision_label", { revision: String(item.revision_number) })}
          </li>
        ))}
      </ul>
    </details>
  );
}
