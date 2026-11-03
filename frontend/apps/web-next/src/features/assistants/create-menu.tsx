import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, LayoutTemplate, Users } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Switch } from "@astryxdesign/core/Switch";
import { TextInput } from "@/components/astryx/text-input";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { revealProblems } from "@/components/composites/field-problem";
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
  // Opened from a menu item, gone once the dialog is up (a tap leaves focus in
  // the closed menu): focus goes back to the menu button.
  const noTrigger = useRef<HTMLElement | null>(null);
  useReturnFocus(dialog === "group-chat", noTrigger);

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
          label={t("create_assistant")}
          variant="primary"
          // Astryx keeps a label on one line at a fixed height and cuts it with an
          // ellipsis; this one may shrink at 320 px, so it wraps instead (1.4.4).
          // A line and py-1 fit the element height, which min-h keeps, so one
          // line is exactly as tall as the menu button beside it.
          className={
            "h-auto min-h-(--size-element-md) min-w-0 shrink grow rounded-r-none py-1 text-center whitespace-normal"
          }
          isLoading={createAssistant.isPending}
          isInterruptible
          onClick={createBlankAssistant}
        />
        <DropdownMenu
          button={{
            label: t("ui_more_ways_to_create"),
            icon: <ChevronDown aria-hidden="true" />,
            isIconOnly: true,
            variant: "primary",
            className: "rounded-l-none border-l"
          }}
          hasChevron={false}
          alignment="end"
          items={[
            {
              label: t("create_new_assistant"),
              icon: <Bot aria-hidden="true" />,
              onClick: createBlankAssistant
            },
            ...(settings.using_templates
              ? [
                  {
                    label: t("start_with_template"),
                    icon: <LayoutTemplate aria-hidden="true" />,
                    onClick: () => setDialog("template")
                  }
                ]
              : []),
            {
              label: t("create_new_group_chat"),
              icon: <Users aria-hidden="true" />,
              onClick: createBlankGroupChat
            }
          ]}
        />
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
                  <Button
                    label={t("cancel")}
                    isDisabled={pending}
                    onClick={() => closeGroupDialog(false)}
                  />
                  <Button
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
