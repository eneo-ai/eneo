"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
import { useSpace } from "@/features/spaces/use-space";

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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setName("");
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
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) onCreate(name.trim());
          }}
        >
          <Label htmlFor="chat-app-name">{nameLabel}</Label>
          <Input
            id="chat-app-name"
            value={name}
            placeholder={`${t("name")}...`}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </form>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={pending || !name.trim()} onClick={() => onCreate(name.trim())}>
            {pending ? t("loading") : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Split button: primary action creates an assistant, the chevron menu also
 * offers group chats. Template-based creation is deferred (tracked in the
 * migration ledger); creation here is always blank.
 */
export function CreateChatAppMenu() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"assistant" | "group-chat" | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const createAssistant = useMutation({
    mutationFn: (name: string) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/assistants/", {
          params: { path: { id: space.id } },
          body: { name }
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
            <Button size="icon" className="rounded-l-none border-l" aria-label={t("actions")}>
              <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setDialog("assistant")}>
              <Bot className="size-4" /> {t("create_new_assistant")}
            </DropdownMenuItem>
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
        onCreate={(name) => createAssistant.mutate(name)}
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
