"use client";

import { useTranslations } from "next-intl";
import { Textarea } from "@/components/ui/textarea";

/** Free-text input for a `text-field` app input. */
export function TextInput({
  value,
  description,
  onChange
}: {
  value: string;
  description?: string | null;
  onChange: (value: string) => void;
}) {
  const t = useTranslations();
  return (
    <div className="w-full max-w-[80ch] min-w-0">
      <Textarea
        aria-label={t("enter_your_question_here")}
        value={value}
        rows={4}
        placeholder={description || t("enter_text_here")}
        className="bg-background max-h-[40vh] resize-none rounded-2xl px-6 py-3 text-base shadow-sm"
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
