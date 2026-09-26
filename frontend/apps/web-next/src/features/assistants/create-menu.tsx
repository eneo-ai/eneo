"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, LayoutTemplate, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { TemplateGalleryDialog } from "@/features/templates/template-gallery-dialog";

/** Names what is created. A missing name shows at the field on create, which takes focus. */
function CreateDialog({
  open,
  onOpenChange,
  title,
  description,
  nameLabel,
  confirmLabel,
  pending,
  onCreate
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  nameLabel: string;
  confirmLabel: string;
  pending: boolean;
  onCreate: (name: string) => void;
}) {
  const t = useTranslations();
  const [name, setName] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const nameProblem = submitted && !name.trim() ? t("required_field") : null;

  function create() {
    if (pending) return;
    if (!name.trim()) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      nameRef.current?.focus();
      return;
    }
    onCreate(name.trim());
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setName("");
          setSubmitted(false);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <form
          className="flex flex-col gap-2"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            create();
          }}
        >
          <Label htmlFor="chat-app-name">{nameLabel}</Label>
          <Input
            ref={nameRef}
            id="chat-app-name"
            value={name}
            placeholder={`${t("name")}...`}
            onChange={(event) => setName(event.target.value)}
            {...fieldProblemProps("chat-app-name", nameProblem)}
          />
          <FieldProblem id="chat-app-name" problem={nameProblem} />
        </form>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button aria-busy={pending || undefined} onClick={create}>
            {pending ? t("loading") : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Split button: primary action creates a blank assistant; the chevron menu also
 * offers a group chat and — when the tenant has templates enabled — creation
 * from a template gallery (passes from_template).
 */
export function CreateChatAppMenu() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const { settings } = useAppContext();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"assistant" | "group-chat" | "template" | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const createAssistant = useMutation({
    mutationFn: ({
      name,
      fromTemplate
    }: {
      name: string;
      fromTemplate?: Schema<"TemplateCreate">;
    }) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/assistants/", {
          params: { path: { id: space.id } },
          body: {
            name,
            ...(fromTemplate ? { from_template: fromTemplate } : {})
          }
        })
      ),
    onSuccess: (assistant) => {
      invalidate();
      setDialog(null);
      router.push(`/spaces/${routeId}/assistants/${assistant.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  const createGroupChat = useMutation({
    mutationFn: (name: string) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/group-chats/", {
          params: { path: { id: space.id } },
          body: { name }
        })
      ),
    onSuccess: (groupChat) => {
      invalidate();
      setDialog(null);
      router.push(`/spaces/${routeId}/group-chats/${groupChat.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <div className="flex">
        <Button className="rounded-r-none" onClick={() => setDialog("assistant")}>
          {t("create_assistant")}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon"
              className="rounded-l-none border-l"
              aria-label={t("ui_more_ways_to_create")}
            >
              <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDialog("assistant")}>
              <Bot className="size-4" /> {t("create_new_assistant")}
            </DropdownMenuItem>
            {settings.using_templates && (
              <DropdownMenuItem onSelect={() => setDialog("template")}>
                <LayoutTemplate className="size-4" /> {t("start_with_template")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => setDialog("group-chat")}>
              <Users className="size-4" /> {t("create_new_group_chat")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <CreateDialog
        open={dialog === "assistant"}
        onOpenChange={(open) => setDialog(open ? "assistant" : null)}
        title={t("create_new_assistant")}
        nameLabel={t("name")}
        confirmLabel={t("create_assistant")}
        pending={createAssistant.isPending}
        onCreate={(name) => createAssistant.mutate({ name })}
      />
      <TemplateGalleryDialog
        templateKind="assistant"
        createLabel={t("create_assistant")}
        open={dialog === "template"}
        onOpenChange={(open) => setDialog(open ? "template" : null)}
        pending={createAssistant.isPending}
        onCreate={(fromTemplate, name) =>
          createAssistant.mutateAsync({ name, fromTemplate }).then(() => undefined)
        }
      />
      <CreateDialog
        open={dialog === "group-chat"}
        onOpenChange={(open) => setDialog(open ? "group-chat" : null)}
        title={t("create_a_new_group_chat")}
        description={t("group_chats_intro_text")}
        nameLabel={t("group_chat_name")}
        confirmLabel={t("create_group_chat")}
        pending={createGroupChat.isPending}
        onCreate={(name) => createGroupChat.mutate(name)}
      />
    </>
  );
}
