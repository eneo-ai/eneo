"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type SubmitEvent } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getErrorMessage } from "@/lib/api/errors";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import {
  deriveSkillSlug,
  normalizedSkillContent,
  type SkillContent,
  type SkillCreation
} from "./skill-model";

type Props =
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
    };

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
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);
  const instructionsRef = useRef<HTMLTextAreaElement>(null);
  const slugRef = useRef<HTMLInputElement>(null);
  const dirty =
    name !== baseline.name ||
    description !== baseline.description ||
    instructions !== baseline.instructions ||
    (props.mode === "create" && slug !== baseline.slug);

  useBeforeUnloadWarning(dirty);

  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setAttempted(true);
    setError(null);
    const content = normalizedSkillContent({
      display_name: name,
      description,
      instructions
    });
    const submittedSlug = slug.trim();
    if (!content.display_name) nameRef.current?.focus();
    else if (!content.description) descriptionRef.current?.focus();
    else if (!content.instructions) instructionsRef.current?.focus();
    else if (props.mode === "create" && !submittedSlug) {
      document.getElementById(`${id}-advanced`)?.setAttribute("open", "");
      slugRef.current?.focus();
    } else {
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
        setError(getErrorMessage(cause, t));
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
            ref={nameRef}
            id={`${id}-name`}
            value={name}
            maxLength={200}
            required
            disabled={busy}
            aria-invalid={attempted && !name.trim()}
            onChange={(event) => {
              setName(event.target.value);
              if (props.mode === "create" && !slugCustomized)
                setSlug(deriveSkillSlug(event.target.value));
            }}
          />
          <p className="text-muted-foreground text-xs">{t("skills_display_name_description")}</p>
          {attempted && !name.trim() && (
            <p className="text-destructive text-xs">{t("skills_required_field")}</p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${id}-description`}>{t("skills_description_label")}</Label>
          <Textarea
            ref={descriptionRef}
            id={`${id}-description`}
            value={description}
            rows={3}
            maxLength={1024}
            required
            disabled={busy}
            aria-invalid={attempted && !description.trim()}
            onChange={(event) => setDescription(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("skills_description_description")}</p>
          {attempted && !description.trim() && (
            <p className="text-destructive text-xs">{t("skills_required_field")}</p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${id}-instructions`}>{t("skills_instructions_label")}</Label>
          <Textarea
            ref={instructionsRef}
            id={`${id}-instructions`}
            value={instructions}
            rows={props.mode === "create" ? 8 : 12}
            className="max-h-[50dvh] min-h-48 overflow-y-auto font-mono text-sm"
            required
            disabled={busy}
            aria-invalid={attempted && !instructions.trim()}
            onChange={(event) => setInstructions(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("skills_instructions_description")}</p>
          {attempted && !instructions.trim() && (
            <p className="text-destructive text-xs">{t("skills_required_field")}</p>
          )}
        </div>
        {props.mode === "create" && (
          <details id={`${id}-advanced`} className="rounded-lg border p-4">
            <summary className="cursor-pointer text-sm font-medium">
              {t("skills_advanced_options")}
            </summary>
            <div className="mt-4 space-y-2">
              <Label htmlFor={`${id}-slug`}>{t("skills_slug_label")}</Label>
              <Input
                ref={slugRef}
                id={`${id}-slug`}
                value={slug}
                maxLength={64}
                autoComplete="off"
                required
                disabled={busy}
                aria-invalid={attempted && !slug.trim()}
                onChange={(event) => {
                  setSlug(event.target.value);
                  setSlugCustomized(true);
                }}
              />
              <p className="text-muted-foreground text-xs">{t("skills_slug_description")}</p>
              {attempted && !slug.trim() && (
                <p className="text-destructive text-xs">{t("skills_required_field")}</p>
              )}
            </div>
          </details>
        )}
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>
              {t(
                props.mode === "create"
                  ? "skills_form_error_title"
                  : "skills_revision_form_error_title"
              )}
            </AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
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
  );
}
