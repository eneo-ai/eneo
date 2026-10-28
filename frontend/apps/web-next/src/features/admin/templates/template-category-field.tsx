"use client";

import { useTranslations } from "next-intl";
import { useId, useState, type Ref } from "react";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { TEMPLATE_CATEGORIES, predefinedCategory, type TemplateKind } from "./templates";

/**
 * A template's category: one of the kind's predefined categories, each with
 * its description, or a custom one typed by the admin (the Svelte
 * ImprovedCategorySelector). Switching between the two keeps what was chosen
 * in each, so switching back restores it. `problem` shows at the custom field,
 * the only one that can be left empty.
 */
export function TemplateCategoryField({
  kind,
  value,
  onChange,
  problem,
  customRef
}: {
  kind: TemplateKind;
  value: string;
  onChange: (value: string) => void;
  problem: string | null;
  customRef?: Ref<HTMLInputElement>;
}) {
  const t = useTranslations();
  const id = useId();
  const categories = TEMPLATE_CATEGORIES[kind];
  const selected = predefinedCategory(kind, value);
  const [custom, setCustom] = useState(() => !predefinedCategory(kind, value));
  const [lastPredefined, setLastPredefined] = useState(() =>
    predefinedCategory(kind, value) ? value : categories[0]!.value
  );
  const [lastCustom, setLastCustom] = useState(() =>
    predefinedCategory(kind, value) ? "" : value
  );

  function changeMode(next: string) {
    const toCustom = next === "custom";
    if (toCustom === custom) return;
    setCustom(toCustom);
    onChange(toCustom ? lastCustom : lastPredefined);
  }

  return (
    <div className="flex flex-col gap-3">
      <RadioGroup
        value={custom ? "custom" : "predefined"}
        onValueChange={changeMode}
        className="grid grid-cols-2 gap-2"
        aria-label={t("category")}
      >
        {(["predefined", "custom"] as const).map((mode) => (
          <div key={mode} className="flex items-center gap-2">
            <RadioGroupItem value={mode} id={`${id}-${mode}`} />
            <Label htmlFor={`${id}-${mode}`} className="font-normal">
              {t(mode)}
            </Label>
          </div>
        ))}
      </RadioGroup>
      {custom ? (
        <div className="flex flex-col gap-1.5">
          <Input
            ref={customRef}
            value={value}
            required
            placeholder={t("category_name_placeholder")}
            aria-label={t("category")}
            onChange={(event) => {
              setLastCustom(event.target.value);
              onChange(event.target.value);
            }}
            {...fieldProblemProps(`${id}-custom`, problem, `${id}-custom-help`)}
          />
          <p id={`${id}-custom-help`} className="text-muted-foreground text-sm">
            {t("custom_category_help")}
          </p>
          <FieldProblem id={`${id}-custom`} problem={problem} />
        </div>
      ) : (
        <Select
          value={value}
          onValueChange={(next) => {
            setLastPredefined(next);
            onChange(next);
          }}
        >
          <SelectTrigger aria-label={t("select_category")} className="w-full">
            {/* The title only: the options also carry their description. */}
            <SelectValue placeholder={t("select_category")}>
              {selected ? t(selected.title) : undefined}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {categories.map((category) => (
              <SelectItem key={category.value} value={category.value} textValue={t(category.title)}>
                <span className="flex flex-col items-start gap-0.5 py-0.5">
                  <span className="font-medium">{t(category.title)}</span>
                  <span className="text-muted-foreground text-xs whitespace-normal">
                    {t(category.description)}
                  </span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
