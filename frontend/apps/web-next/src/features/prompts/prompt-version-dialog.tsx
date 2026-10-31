"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { ClientTime } from "@/components/composites/client-time";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import {
  LeaveConfirmation,
  type LeaveConfirmationHandle
} from "@/components/composites/leave-confirmation";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";

type PromptResource = { type: "assistant" | "app"; id: string };
type Props = {
  resource: PromptResource;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUseVersion: (prompt: Schema<"PromptPublic">) => void;
};
type Action =
  { kind: "description"; id: string; description: string } | { kind: "delete"; id: string };

async function fetchPromptVersions(resource: PromptResource, signal: AbortSignal) {
  return resource.type === "assistant"
    ? (
        await unwrap(
          browserApi.GET("/api/v1/assistants/{id}/prompts/", {
            params: { path: { id: resource.id } },
            signal
          })
        )
      ).items
    : (
        await unwrap(
          browserApi.GET("/api/v1/apps/{id}/prompts/", {
            params: { path: { id: resource.id } },
            signal
          })
        )
      ).items;
}

/** The dialog persists; its resource-scoped history/draft is discarded when it closes. */
export function PromptVersionDialog(props: Props) {
  const t = useTranslations();
  const leave = useRef<LeaveConfirmationHandle>(null);
  function changeOpen(next: boolean) {
    if (next) props.onOpenChange(true);
    else if (leave.current) leave.current.confirm(() => props.onOpenChange(false));
    else props.onOpenChange(false);
  }
  return (
    <Dialog
      isOpen={props.open}
      aria-label={t("prompt_history")}
      onOpenChange={changeOpen}
      purpose="form"
      width={840}
      maxHeight="85dvh"
    >
      {props.open && (
        <History
          key={`${props.resource.type}:${props.resource.id}`}
          {...props}
          requestClose={() => changeOpen(false)}
          leave={leave}
        />
      )}
    </Dialog>
  );
}

function History({
  resource,
  onOpenChange,
  onUseVersion,
  requestClose,
  leave
}: Props & { requestClose: () => void; leave: React.Ref<LeaveConfirmationHandle> }) {
  const t = useTranslations();
  const { user } = useAppContext();
  const client = useQueryClient();
  const discard = useRef<LeaveConfirmationHandle>(null);
  const listKey = [resource.type, resource.id, "prompts"];
  const [selection, setSelection] = useState<string | null>(null);
  const [step, setStep] = useState<"preview" | "description" | "delete">("preview");
  const [description, setDescription] = useState("");
  const body = useRef<HTMLDivElement>(null);
  const actionHeading = useRef<HTMLHeadingElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current !== step) {
      if (step === "preview") (editButton.current ?? body.current)?.focus();
      else actionHeading.current?.focus();
      previousStep.current = step;
    }
  }, [step]);
  const list = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) => fetchPromptVersions(resource, signal),
    staleTime: 0
  });
  const selected =
    list.data?.find((v) => v.id === selection) ??
    list.data?.find((v) => v.is_selected) ??
    list.data?.[0];
  const preview = useQuery({
    queryKey: ["prompt", selected?.id],
    enabled: !!selected,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/prompts/{id}/", { params: { path: { id: selected!.id } }, signal })
      ),
    staleTime: 0
  });
  const author = selected?.user.id === user.id;
  const mutation = useMutation({
    mutationFn: async (action: Action) => {
      if (action.kind === "delete") {
        await unwrap(
          browserApi.DELETE("/api/v1/prompts/{id}/", { params: { path: { id: action.id } } })
        );
        return null;
      }
      return unwrap(
        browserApi.PATCH("/api/v1/prompts/{id}/", {
          params: { path: { id: action.id } },
          body: { description: action.description }
        })
      );
    },
    onMutate: async (action) => {
      await Promise.all([
        client.cancelQueries({ queryKey: listKey }),
        client.cancelQueries({ queryKey: ["prompt", action.id] })
      ]);
    },
    onSuccess: (saved, action) => {
      if (saved) {
        client.setQueryData(["prompt", action.id], saved);
        client.setQueryData<Schema<"PromptSparse">[]>(listKey, (current) =>
          current?.map((v) => (v.id === action.id ? { ...v, description: saved.description } : v))
        );
      } else {
        client.removeQueries({ queryKey: ["prompt", action.id], exact: true });
        client.setQueryData<Schema<"PromptSparse">[]>(listKey, (current) =>
          current?.filter((v) => v.id !== action.id)
        );
        setSelection(null);
      }
      if (saved && selected?.is_selected)
        void client.invalidateQueries({
          queryKey: [resource.type === "assistant" ? "assistants" : "apps", resource.id]
        });
      setStep("preview");
      void client.invalidateQueries({ queryKey: listKey });
    },
    onError: (error) => toastApiError(error, t)
  });
  useImperativeHandle(
    leave,
    () => ({
      confirm(action) {
        if (!mutation.isPending) discard.current?.confirm(action);
      }
    }),
    [mutation.isPending]
  );
  const dirty = step === "description" && description !== (preview.data?.description ?? "");
  const actionTitle = step === "delete" ? t("delete_prompt") : t("edit_prompt_description");
  function submit() {
    if (mutation.isPending || !selected || !author) return;
    if (step === "delete" && !selected.is_selected)
      mutation.mutate({ kind: "delete", id: selected.id });
    if (step === "description")
      mutation.mutate({ kind: "description", id: selected.id, description });
  }
  return (
    <>
      <DialogHeader
        title={t("prompt_history")}
        onOpenChange={(next) => {
          if (!next) requestClose();
        }}
      />
      <div
        ref={body}
        tabIndex={-1}
        className="focus-visible:outline-ring flex min-h-0 flex-col gap-4 overflow-y-auto py-4 focus-visible:outline-2"
      >
        {step !== "preview" ? (
          <>
            <h3
              ref={actionHeading}
              tabIndex={-1}
              className="focus-visible:outline-ring rounded-ax-inner text-lg font-medium focus-visible:outline-2"
            >
              {actionTitle}
            </h3>
            {step === "delete" ? (
              <p>{t("do_you_really_want_to_delete_this_version")}</p>
            ) : (
              <TextArea
                label={t("description")}
                value={description}
                onChange={setDescription}
                isReadOnly={mutation.isPending}
              />
            )}
            {mutation.isError && <ListError error={mutation.error} title={t("request_failed")} />}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                label={t("cancel")}
                isDisabled={mutation.isPending}
                onClick={() => {
                  mutation.reset();
                  setStep("preview");
                }}
              />
              <Button
                label={t(step === "delete" ? "delete" : "save_changes")}
                variant={step === "delete" ? "destructive" : "primary"}
                isLoading={mutation.isPending}
                isInterruptible
                onClick={submit}
              />
            </div>
          </>
        ) : (
          <QueryStateBoundary query={list} rows={2}>
            {(versions) =>
              versions.length === 0 ? (
                <p>{t("prompt_library_versions_empty")}</p>
              ) : (
                <div className="grid min-h-0 grid-cols-1 gap-4 sm:grid-cols-[16rem_1fr]">
                  <ul className="border-ax-border rounded-ax-container flex max-h-48 flex-col gap-1 overflow-y-auto border p-2 sm:max-h-[55dvh]">
                    {versions.map((version) => (
                      <li key={version.id}>
                        <button
                          type="button"
                          aria-current={version.id === selected?.id ? "true" : undefined}
                          className={cn(
                            "focus-visible:outline-ring hover:bg-ax-hover rounded-ax-inner flex min-h-11 w-full flex-col gap-1 px-3 py-2 text-start text-sm focus-visible:outline-2",
                            version.id === selected?.id && "bg-ax-accent-muted"
                          )}
                          onClick={() => setSelection(version.id)}
                        >
                          <span>
                            {version.created_at ? (
                              <ClientTime value={version.created_at} format="date_time" />
                            ) : (
                              version.id.slice(0, 8)
                            )}{" "}
                            {version.is_selected && <strong>{t("current_version")}</strong>}
                          </span>
                          <span className="text-ax-text-secondary break-words">
                            {t("author")}: {version.user.username || version.user.email}
                          </span>
                          {version.description && (
                            <span className="text-ax-text-secondary line-clamp-2">
                              {version.description}
                            </span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                  <QueryStateBoundary query={preview} rows={2}>
                    {(prompt) => (
                      <div className="flex min-w-0 flex-col gap-4">
                        <pre className="bg-ax-sunken rounded-ax-inner max-h-[35dvh] overflow-y-auto p-3 text-sm break-words whitespace-pre-wrap">
                          {prompt.text}
                        </pre>
                        {prompt.description && (
                          <p className="bg-ax-accent-muted rounded-ax-inner p-3 text-sm break-words whitespace-pre-wrap">
                            {prompt.description}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-2">
                          <Tooltip
                            content={author ? undefined : t("only_author_can_change_description")}
                          >
                            <span tabIndex={author ? undefined : 0}>
                              <Button
                                ref={editButton}
                                label={t(
                                  prompt.description ? "edit_description" : "add_description"
                                )}
                                isDisabled={!author}
                                onClick={() => {
                                  if (!author) return;
                                  mutation.reset();
                                  setDescription(prompt.description ?? "");
                                  setStep("description");
                                }}
                              />
                            </span>
                          </Tooltip>
                          <Tooltip
                            content={author ? undefined : t("prompt_only_author_can_delete")}
                          >
                            <span tabIndex={author ? undefined : 0}>
                              <Button
                                label={t("delete_prompt")}
                                isDisabled={!author || selected?.is_selected}
                                onClick={() => {
                                  if (!author || selected?.is_selected) return;
                                  mutation.reset();
                                  setStep("delete");
                                }}
                              />
                            </span>
                          </Tooltip>
                          <Button
                            label={t("restore_this_version")}
                            variant="primary"
                            isDisabled={selected?.is_selected}
                            isLoading={preview.isFetching}
                            isInterruptible
                            onClick={() => {
                              if (selected?.is_selected || preview.isFetching) return;
                              onUseVersion(prompt);
                              onOpenChange(false);
                            }}
                          />
                        </div>
                      </div>
                    )}
                  </QueryStateBoundary>
                </div>
              )
            }
          </QueryStateBoundary>
        )}
      </div>
      <LeaveConfirmation ref={discard} active={dirty && !mutation.isPending} />
    </>
  );
}
