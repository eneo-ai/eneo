"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, LayoutTemplate, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { useAppContext } from "@/components/providers/app-context";
import { markJustCreated } from "@/features/spaces/just-created";
import { createWithUniqueName } from "@/features/spaces/unique-name";
import { useSpace } from "@/features/spaces/use-space";
import { TemplateGalleryDialog } from "@/features/templates/template-gallery-dialog";

/**
 * Split button: the primary action creates a blank assistant at once, named
 * "Ny assistent" (numbered on a collision), and opens its editor, which
 * focuses the name. No name dialog in between: the editor's first field is
 * that same name. The chevron menu also offers a group chat, created the same
 * way, and — when the tenant has templates enabled — creation from a template
 * gallery (passes from_template), which still asks for the template and name.
 */
export function CreateChatAppMenu() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const { settings } = useAppContext();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"template" | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const createAssistant = useMutation({
    mutationFn: ({
      name,
      fromTemplate
    }: {
      name: string;
      fromTemplate?: Schema<"TemplateCreate">;
    }) =>
      createWithUniqueName(name, (candidate) =>
        unwrap(
          browserApi.POST("/api/v1/spaces/{id}/applications/assistants/", {
            params: { path: { id: space.id } },
            body: {
              name: candidate,
              ...(fromTemplate ? { from_template: fromTemplate } : {})
            }
          })
        )
      ),
    onSuccess: (assistant, { fromTemplate }) => {
      invalidate();
      setDialog(null);
      if (!fromTemplate) markJustCreated("assistant", assistant.id);
      router.push(`/spaces/${routeId}/assistants/${assistant.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  const createGroupChat = useMutation({
    mutationFn: (name: string) =>
      createWithUniqueName(name, (candidate) =>
        unwrap(
          browserApi.POST("/api/v1/spaces/{id}/applications/group-chats/", {
            params: { path: { id: space.id } },
            body: { name: candidate }
          })
        )
      ),
    onSuccess: (groupChat) => {
      invalidate();
      markJustCreated("group-chat", groupChat.id);
      router.push(`/spaces/${routeId}/group-chats/${groupChat.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  // Busy, the buttons stay enabled so they keep focus; a second press is ignored.
  const pending = createAssistant.isPending || createGroupChat.isPending;
  const createBlankAssistant = () => {
    if (!pending) createAssistant.mutate({ name: t("new_assistant_default_name") });
  };
  const createBlankGroupChat = () => {
    if (!pending) createGroupChat.mutate(t("new_group_chat_default_name"));
  };

  return (
    <>
      <div className="flex">
        <Button
          className="rounded-r-none"
          aria-busy={createAssistant.isPending || undefined}
          onClick={createBlankAssistant}
        >
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
            <DropdownMenuItem onSelect={createBlankAssistant}>
              <Bot className="size-4" /> {t("create_new_assistant")}
            </DropdownMenuItem>
            {settings.using_templates && (
              <DropdownMenuItem onSelect={() => setDialog("template")}>
                <LayoutTemplate className="size-4" /> {t("start_with_template")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={createBlankGroupChat}>
              <Users className="size-4" /> {t("create_new_group_chat")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
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
    </>
  );
}
