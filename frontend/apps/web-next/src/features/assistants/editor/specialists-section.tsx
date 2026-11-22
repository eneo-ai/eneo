import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { revealProblems } from "@/components/composites/field-problem";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { useSpace } from "@/features/spaces/use-space";
import { useUpdateAssistant, type Assistant, type AssistantUpdate } from "./use-assistant";

export function SpecialistsSection({
  assistant,
  supportsTools
}: {
  assistant: Pick<Assistant, "id" | "permissions" | "specialists">;
  supportsTools: boolean;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("specialists");
  const [selected, setSelected] = useState("");
  const [description, setDescription] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const saved = assistant.specialists ?? [];
  // A visible saved link remains editable even when it is absent from the picker catalog.
  const candidates = new Map(
    saved.map((item) => [item.id, { name: item.handle, description: item.default_description }])
  );
  for (const item of space.applications?.assistants.items ?? []) {
    if (item.id !== assistant.id)
      candidates.set(item.id, { name: item.name, description: item.description });
  }
  const candidate = candidates.get(selected);
  const member = saved.find((item) => item.id === selected);
  const required = !candidate?.description?.trim();
  const invalid = required && !description.trim();
  const editable = assistant.permissions?.includes("edit");

  function select(id: string) {
    setSelected(id);
    setDescription(saved.find((item) => item.id === id)?.user_description ?? "");
    setSubmitted(false);
  }

  async function persist(specialists: NonNullable<AssistantUpdate["specialists"]>) {
    const result = await autosave(() => update.mutateAsync({ specialists }));
    if (result !== undefined) select("");
  }

  const members = saved.map(({ id, user_description }) => ({ id, user_description }));
  return (
    <SettingsGroup title={t("specialists")} description={t("specialists_description")}>
      {saved.map((item) => (
        <SettingsRow key={item.id} title={item.handle}>
          {item.user_description || item.default_description}
        </SettingsRow>
      ))}
      {editable && (
        <SettingsRow
          description={
            supportsTools ? t("specialists_depth_note") : t("specialists_need_tool_model")
          }
        >
          <Selector
            label={t("specialists")}
            hasSearch
            value={selected}
            placeholder={t("choose_a_specialist_to_add")}
            isDisabled={update.isPending}
            options={[...candidates].map(([value, { name: label }]) => ({ value, label }))}
            onChange={select}
          />
          {candidate && (
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (invalid) {
                  revealProblems(() => setSubmitted(true), field.current);
                  return;
                }
                const link = { id: selected, user_description: description.trim() || null };
                void persist(
                  member
                    ? members.map((item) => (item.id === selected ? link : item))
                    : [...members, link]
                );
              }}
              noValidate
            >
              <TextArea
                ref={field}
                label={t("specialist_role")}
                description={t("specialist_role_help")}
                value={description}
                onChange={setDescription}
                placeholder={candidate.description ?? undefined}
                isRequired={required}
                isDisabled={update.isPending}
                status={
                  submitted && invalid
                    ? { type: "error", message: t("specialist_description_required") }
                    : undefined
                }
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  variant="primary"
                  isDisabled={update.isPending}
                  label={t(member ? "save" : "add_specialist")}
                />
                {member && (
                  <Button
                    label={t("remove_specialist")}
                    isDisabled={update.isPending}
                    onClick={() => void persist(members.filter((item) => item.id !== selected))}
                  />
                )}
              </div>
            </form>
          )}
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}
