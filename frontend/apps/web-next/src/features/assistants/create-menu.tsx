import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, LayoutTemplate, Users } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { revealProblems } from "@/components/composites/field-problem";
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
 * that same name. The chevron menu also offers a named group chat with a choice
 * to open its editor, and — when the tenant has templates enabled — creation from a template
 * gallery (passes from_template), which still asks for the template and name.
 */
export function CreateChatAppMenu() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const { settings } = useAppContext();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"template" | "group-chat" | null>(null);
  const groupFormId = useId();
  const groupNameRef = useRef<HTMLInputElement>(null);
  const [groupName, setGroupName] = useState("");
  const [openGroupEditor, setOpenGroupEditor] = useState(true);
  const [groupNameMissing, setGroupNameMissing] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const createAssistant = useMutation({
    mutationFn: ({
      name,
      fromTemplate
    }: {
      name: string;
      fromTemplate?: Schema<"TemplateCreate">;
      openEditor?: boolean;
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
    onSuccess: (assistant, { fromTemplate, openEditor = !fromTemplate }) => {
      invalidate();
      setDialog(null);
      if (openEditor) {
        if (!fromTemplate) markJustCreated("assistant", assistant.id);
        router.push(`/spaces/${routeId}/assistants/${assistant.id}/edit`);
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  const createGroupChat = useMutation({
    mutationFn: ({ name }: { name: string; openEditor: boolean }) =>
      createWithUniqueName(name, (candidate) =>
        unwrap(
          browserApi.POST("/api/v1/spaces/{id}/applications/group-chats/", {
            params: { path: { id: space.id } },
            body: { name: candidate }
          })
        )
      ),
    onSuccess: (groupChat, { openEditor }) => {
      invalidate();
      setDialog(null);
      if (openEditor) {
        markJustCreated("group-chat", groupChat.id);
        router.push(`/spaces/${routeId}/group-chats/${groupChat.id}/edit`);
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  // Busy, the buttons stay enabled so they keep focus; a second press is ignored.
  const pending = createAssistant.isPending || createGroupChat.isPending;
  const createBlankAssistant = () => {
    if (!pending) createAssistant.mutate({ name: t("new_assistant_default_name") });
  };
  const createBlankGroupChat = () => {
    if (pending) return;
    setGroupName("");
    setGroupNameMissing(false);
    setOpenGroupEditor(true);
    setDialog("group-chat");
  };
  const closeGroupDialog = (open: boolean) => {
    if (!open && !pending) setDialog(null);
  };
  const submitGroupChat = (event: React.SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const name = groupName.trim();
    if (!name) {
      revealProblems(() => setGroupNameMissing(true), groupNameRef.current);
      return;
    }
    createGroupChat.mutate({ name, openEditor: openGroupEditor });
  };

  return (
    <>
      <div className="flex max-w-full">
        <Button
          className="min-w-0 shrink grow rounded-r-none"
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
      <Dialog
        isOpen={dialog === "group-chat"}
        onOpenChange={closeGroupDialog}
        purpose="form"
        width={440}
      >
        <Layout
          height="auto"
          header={
            <DialogHeader title={t("create_a_new_group_chat")} onOpenChange={closeGroupDialog} />
          }
          content={
            dialog === "group-chat" ? (
              <LayoutContent>
                <form
                  id={groupFormId}
                  onSubmit={submitGroupChat}
                  noValidate
                  className="flex flex-col gap-4"
                >
                  <FormLayout defaultOptionality="required">
                    <TextInput
                      ref={groupNameRef}
                      label={t("group_chat_name")}
                      value={groupName}
                      onChange={(name) => {
                        setGroupName(name);
                        if (name.trim()) setGroupNameMissing(false);
                      }}
                      isRequired
                      isReadOnly={pending}
                      htmlName="name"
                      autoComplete="off"
                      status={
                        groupNameMissing
                          ? { type: "error", message: t("required_field") }
                          : undefined
                      }
                    />
                  </FormLayout>
                  <Switch
                    label={t("open_group_chat_editor_after_creation")}
                    value={openGroupEditor}
                    onChange={(value) => {
                      if (!pending) setOpenGroupEditor(value);
                    }}
                    aria-busy={pending || undefined}
                  />
                </form>
              </LayoutContent>
            ) : null
          }
          footer={
            dialog === "group-chat" ? (
              <LayoutFooter>
                <div className="flex flex-wrap justify-end gap-2">
                  <AstryxButton
                    label={t("cancel")}
                    isDisabled={pending}
                    onClick={() => closeGroupDialog(false)}
                  />
                  <AstryxButton
                    type="submit"
                    form={groupFormId}
                    variant="primary"
                    label={t("create_group_chat")}
                    isLoading={createGroupChat.isPending}
                    isInterruptible
                  />
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>
      <TemplateGalleryDialog
        templateKind="assistant"
        createLabel={t("create_assistant")}
        open={dialog === "template"}
        onOpenChange={(open) => setDialog(open ? "template" : null)}
        pending={createAssistant.isPending}
        onCreate={(fromTemplate, name, openEditor) =>
          createAssistant.mutateAsync({ name, fromTemplate, openEditor }).then(() => undefined)
        }
      />
    </>
  );
}
