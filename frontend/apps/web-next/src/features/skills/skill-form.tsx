"use client";

import { useTranslations } from "use-intl";
import type { ReferenceCatalog } from "@eneo/skill-instructions";
import { SkillInstructionEditor } from "./skill-instruction-editor";
import { useEffect, useId, useState, type SubmitEvent } from "react";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ListError } from "@/components/composites/query-state";
import { LeaveConfirmation } from "@/components/composites/leave-confirmation";
import {
  deriveSkillSlug,
  normalizedSkillContent,
  type SkillContent,
  type SkillCreation
} from "./skill-model";

type Props = {
  referenceCatalog?: ReferenceCatalog;
  referencePickerInline?: boolean;
  onLeave?: () => void;
} & (
  | {
      mode: "create";
      onSubmit: (value: SkillCreation) => Promise<void>;
      initialValue?: never;
      onDirtyChange?: (dirty: boolean) => void;
    }
  | {
      mode: "revision";
      onSubmit: (value: SkillContent) => Promise<void>;
      initialValue: SkillContent;
      onDirtyChange?: (dirty: boolean) => void;
    }
);

export function SkillForm(props: Props) {
  const t = useTranslations();
  const onDirtyChange = props.onDirtyChange;
  const id = useId();
  const initial = props.mode === "revision" ? props.initialValue : null;
  const [name, setName] = useState(initial?.display_name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [instructions, setInstructions] = useState(initial?.instructions ?? "");
  const [slug, setSlug] = useState(deriveSkillSlug(initial?.display_name ?? ""));
  const [slugCustomized, setSlugCustomized] = useState(false);
  const [baseline, setBaseline] = useState({
    name: initial?.display_name ?? "",
    description: initial?.description ?? "",
    instructions: initial?.instructions ?? "",
    slug: deriveSkillSlug(initial?.display_name ?? "")
  });
  const [attempted, setAttempted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const dirty =
    name !== baseline.name ||
    description !== baseline.description ||
    instructions !== baseline.instructions ||
    (props.mode === "create" && slug !== baseline.slug);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const required = (value: string) => (attempted && !value.trim() ? t("required_field") : null);
  const nameProblem = required(name);
  const descriptionProblem = required(description);
  const instructionsProblem = required(instructions);
  const slugProblem = required(slug);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const content = normalizedSkillContent({
      display_name: name,
      description,
      instructions
    });
    const submittedSlug = slug.trim();
    const firstProblem = !content.display_name
      ? `${id}-name`
      : !content.description
        ? `${id}-description`
        : !content.instructions
          ? `${id}-instructions`
          : props.mode === "create" && !submittedSlug
            ? `${id}-slug`
            : null;
    if (firstProblem) {
      revealProblems(() => setAttempted(true), firstProblem);
    } else {
      setAttempted(true);
      setBusy(true);
      try {
        if (props.mode === "create") await props.onSubmit({ ...content, slug: submittedSlug });
        else await props.onSubmit(content);
        setName(content.display_name);
        setDescription(content.description);
        setInstructions(content.instructions);
        setSlug(submittedSlug);
        setBaseline({
          name: content.display_name,
          description: content.description,
          instructions: content.instructions,
          slug: submittedSlug
        });
        setAttempted(false);
        setSaved(true);
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(false);
      }
    }
  }

  function discard() {
    setName(baseline.name);
    setDescription(baseline.description);
    setInstructions(baseline.instructions);
    setSlug(baseline.slug);
    setAttempted(false);
    setError(null);
  }

  return (
    <>
      <form
        className="flex max-w-2xl flex-col gap-6"
        onSubmit={(event) => void submit(event)}
        noValidate
        aria-busy={busy}
      >
        {/* The sticky footer (about 4 rem) must never cover focus (WCAG 2.4.11):
          the fields keep 5 rem of bottom scroll margin, so Tab and focus()
          scroll them into view above it. */}
        <div className="flex flex-col gap-6 [&_*]:scroll-mb-20">
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>{t("skills_display_name_label")}</Label>
            <Input
              id={`${id}-name`}
              value={name}
              maxLength={200}
              required
              disabled={busy}
              {...fieldProblemProps(`${id}-name`, nameProblem)}
              onChange={(event) => {
                setName(event.target.value);
                if (props.mode === "create" && !slugCustomized)
                  setSlug(deriveSkillSlug(event.target.value));
              }}
            />
            <p className="text-muted-foreground text-xs">{t("skills_display_name_description")}</p>
            <FieldProblem id={`${id}-name`} problem={nameProblem} />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-description`}>{t("skills_description_label")}</Label>
            <Textarea
              id={`${id}-description`}
              value={description}
              rows={3}
              maxLength={1024}
              required
              disabled={busy}
              {...fieldProblemProps(`${id}-description`, descriptionProblem)}
              onChange={(event) => setDescription(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">{t("skills_description_description")}</p>
            <FieldProblem id={`${id}-description`} problem={descriptionProblem} />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-instructions`}>{t("skills_instructions_label")}</Label>
            {props.referenceCatalog ? (
              <SkillInstructionEditor
                id={`${id}-instructions`}
                value={instructions}
                onChange={setInstructions}
                disabled={busy}
                invalid={Boolean(instructionsProblem)}
                describedBy={`${id}-instructions-problem`}
                catalog={props.referenceCatalog}
                inlinePicker={props.referencePickerInline}
              />
            ) : (
              <Textarea
                id={`${id}-instructions`}
                value={instructions}
                rows={props.mode === "create" ? 8 : 12}
                className="max-h-[50dvh] min-h-48 overflow-y-auto font-mono text-sm"
                required
                disabled={busy}
                {...fieldProblemProps(`${id}-instructions`, instructionsProblem)}
                onChange={(event) => setInstructions(event.target.value)}
              />
            )}
            {!props.referenceCatalog && (
              <p className="text-muted-foreground text-xs">
                {t("skills_instructions_description")}
              </p>
            )}
            <FieldProblem id={`${id}-instructions`} problem={instructionsProblem} />
          </div>
          {props.mode === "create" && (
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                {t("skills_advanced_options")}
              </summary>
              <div className="mt-4 space-y-2">
                <Label htmlFor={`${id}-slug`}>{t("skills_slug_label")}</Label>
                <Input
                  id={`${id}-slug`}
                  value={slug}
                  maxLength={64}
                  autoComplete="off"
                  required
                  disabled={busy}
                  {...fieldProblemProps(`${id}-slug`, slugProblem)}
                  onChange={(event) => {
                    setSlug(event.target.value);
                    setSlugCustomized(true);
                  }}
                />
                <p className="text-muted-foreground text-xs">{t("skills_slug_description")}</p>
                <FieldProblem id={`${id}-slug`} problem={slugProblem} />
              </div>
            </details>
          )}
          {error != null && (
            <ListError
              error={error}
              title={t(
                props.mode === "create"
                  ? "skills_form_error_title"
                  : "skills_revision_form_error_title"
              )}
            />
          )}
        </div>
        <div className="bg-background sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t py-3">
          <p className="text-muted-foreground text-sm" role="status">
            {dirty ? t("skills_form_unsaved_status") : saved ? t("skills_form_saved_status") : ""}
          </p>
          <div className="flex gap-2">
            {dirty && (
              <Button type="button" variant="outline" disabled={busy} onClick={discard}>
                {t("discard_all_changes")}
              </Button>
            )}
            {/* Busy, it stays enabled so it keeps focus; submit() ignores a second press. */}
            <Button type="submit" aria-busy={busy || undefined}>
              {busy
                ? t(props.mode === "create" ? "skills_creating" : "saving")
                : t(props.mode === "create" ? "skills_create_action" : "save_changes")}
            </Button>
          </div>
        </div>
      </form>
      <LeaveConfirmation active={dirty} onLeave={props.onLeave} />
    </>
  );
}
