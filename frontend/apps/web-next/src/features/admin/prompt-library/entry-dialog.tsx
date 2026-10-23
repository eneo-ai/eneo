"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  type Entry,
  type EntryFull,
  PROMPT_LIBRARY_KEY,
  promptLibraryEntryQueryOptions
} from "./prompt-library";

type Draft = { name: string; description: string; text: string };

const EMPTY: Draft = { name: "", description: "", text: "" };

/**
 * The prompt's fields. An empty name or text is explained at the field on
 * save (WCAG 3.3.1, 3.3.3) and focus moves to the first one; the save button
 * is never disabled, and busy it keeps focus while a second press is ignored.
 */
function EntryForm({
  formId,
  entryId,
  initial,
  onSaved,
  onPendingChange
}: {
  formId: string;
  /** Omitted: create mode. */
  entryId?: string;
  initial: Draft;
  onSaved: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const nameProblem = draft.name.trim() ? null : t("required_field");
  const textProblem = draft.text.trim() ? null : t("required_field");
  const status = (problem: string | null) =>
    submitted && problem ? { type: "error" as const, message: problem } : undefined;

  const save = useMutation({
    mutationFn: (body: {
      name: string;
      description: string | null;
      text: string;
    }): Promise<EntryFull> =>
      entryId
        ? unwrap(
            browserApi.PUT("/api/v1/admin/prompt-library/{id}/", {
              params: { path: { id: entryId } },
              body
            })
          )
        : unwrap(browserApi.POST("/api/v1/admin/prompt-library/", { body })),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: PROMPT_LIBRARY_KEY });
      const message = entryId
        ? t("prompt_library_saved_as_version", {
            name: saved.name,
            version: String(saved.current_version)
          })
        : t("prompt_library_created", { name: saved.name });
      announce(message);
      toast.success(message);
      onSaved();
    },
    onError: (error) => toastApiError(error, t)
  });

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending) return;
    const firstProblem = nameProblem ? nameRef : textProblem ? textRef : null;
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      firstProblem.current?.focus();
      return;
    }
    save.mutate({
      name: draft.name.trim(),
      description: draft.description.trim() || null,
      text: draft.text
    });
  }

  return (
    <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
      <TextInput
        ref={nameRef}
        label={t("name")}
        value={draft.name}
        onChange={(name) => setDraft((current) => ({ ...current, name }))}
        isRequired
        htmlName="name"
        autoComplete="off"
        status={status(nameProblem)}
        width="100%"
      />
      <TextInput
        label={t("description")}
        value={draft.description}
        onChange={(description) => setDraft((current) => ({ ...current, description }))}
        isOptional
        htmlName="description"
        autoComplete="off"
        width="100%"
      />
      <TextArea
        ref={textRef}
        label={t("governance_prompt_form_text_label")}
        description={t("governance_prompt_form_characters", {
          count: String(draft.text.length)
        })}
        value={draft.text}
        onChange={(text) => setDraft((current) => ({ ...current, text }))}
        isRequired
        rows={10}
        htmlName="text"
        hasSpellCheck={false}
        status={status(textProblem)}
        width="100%"
      />
    </form>
  );
}

/**
 * Create or edit a prompt in a dialog. Edit mode loads the full entry (the
 * list is sparse and lacks the text) and offers the version history; the form
 * mounts fresh (keyed) once the initial values are known, so a reopened
 * dialog never shows a stale draft.
 */
export function EntryDialog({
  entry,
  open,
  onOpenChange,
  onShowHistory
}: {
  /** The prompt to edit; null creates a new one. */
  entry: Entry | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Opens the prompt's version history (edit mode only). */
  onShowHistory: (entry: Entry) => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const [pending, setPending] = useState(false);
  // Opened from a row menu, whose item is gone by the time the dialog is up:
  // focus goes back to the menu button.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(open, noTrigger);
  const full = useQuery({
    ...promptLibraryEntryQueryOptions(browserApi, entry?.id ?? ""),
    enabled: open && entry !== null
  });

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    onOpenChange(next);
  }

  const title = entry ? t("governance_prompt_edit_heading") : t("governance_prompt_new_heading");
  const form = (
    <EntryForm
      key={entry ? (full.data?.id ?? "loading") : "new"}
      formId={formId}
      entryId={entry?.id}
      initial={
        full.data
          ? { name: full.data.name, description: full.data.description ?? "", text: full.data.text }
          : EMPTY
      }
      onSaved={() => onOpenChange(false)}
      onPendingChange={setPending}
    />
  );

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={640}>
      <Layout
        height="auto"
        header={<DialogHeader title={title} onOpenChange={requestOpenChange} />}
        content={
          open ? (
            <LayoutContent>
              {entry ? (
                <QueryStateBoundary query={full} rows={3} variant="text">
                  {() => form}
                </QueryStateBoundary>
              ) : (
                form
              )}
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap items-center gap-2">
                {entry ? (
                  <Button
                    variant="ghost"
                    label={t("prompt_library_show_versions")}
                    icon={<History aria-hidden="true" />}
                    // Stays enabled while saving (it keeps focus); the press waits.
                    onClick={() => {
                      if (!pending) onShowHistory(entry);
                    }}
                    className="me-auto"
                  />
                ) : null}
                <Button
                  label={t("cancel")}
                  isDisabled={pending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("save")}
                  // Busy, it stays enabled (aria-busy) and keeps focus; a
                  // second press is ignored by the form.
                  isLoading={pending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
