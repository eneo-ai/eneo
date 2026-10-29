"use client";

import { useTranslations } from "use-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Input } from "@/components/ui/input";
import type { App, InputFieldType } from "../apps";
import { InputTypeSelect } from "./input-type-select";
import { useUpdateApp } from "./use-app";

type EditableField = { type: InputFieldType; description: string };

/**
 * Edits the app's input fields (description + type). Apps are created with a
 * single field; the run page renders one control per field.
 */
export function InputSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);
  const autosave = useAutosave("input");

  const saved: EditableField[] = useMemo(
    () =>
      app.input_fields.map((field) => ({
        type: field.type,
        description: field.description ?? ""
      })),
    [app.input_fields]
  );
  const [fields, setFields] = useState<EditableField[]>(saved);

  // Adopt server changes (our own save landing) unless the user diverged.
  const savedKey = JSON.stringify(saved);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    setFields((current) => (JSON.stringify(current) === previous ? saved : current));
  }, [savedKey, saved]);

  const fieldsKey = (items: EditableField[]) => JSON.stringify(items);

  const persist = (next: EditableField[], previous: EditableField[] = fields) => {
    const attemptedKey = fieldsKey(next);
    return autosave(() =>
      update.mutateAsync({
        input_fields: next.map((field) => ({
          type: field.type,
          description: field.description || null
        }))
      })
    ).then((result) => {
      if (result !== undefined) return result;
      setFields((current) => (fieldsKey(current) === attemptedKey ? previous : current));
      return undefined;
    });
  };

  function patchField(index: number, patch: Partial<EditableField>, save = true) {
    const previous = fields;
    const next = fields.map((field, position) =>
      position === index ? { ...field, ...patch } : field
    );
    setFields(next);
    if (save) void persist(next, previous);
  }

  return (
    <SettingsGroup title={t("input")}>
      {fields.map((field, index) => (
        <div key={index} className="flex flex-col gap-8">
          <SettingsRow
            title={t("input_description")}
            description={t("input_description_description")}
            htmlFor={`app-input-${index}-description`}
          >
            <Input
              id={`app-input-${index}-description`}
              value={field.description}
              onChange={(event) => patchField(index, { description: event.target.value }, false)}
              onBlur={() => void persist(fields)}
            />
          </SettingsRow>
          <SettingsRow
            title={t("input_type")}
            description={t("input_type_description")}
            htmlFor={`app-input-${index}-type`}
          >
            <InputTypeSelect
              id={`app-input-${index}-type`}
              value={field.type}
              onChange={(type) => patchField(index, { type })}
            />
          </SettingsRow>
        </div>
      ))}
    </SettingsGroup>
  );
}
