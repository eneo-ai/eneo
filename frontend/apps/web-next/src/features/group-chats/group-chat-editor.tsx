"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { IconField } from "@/components/composites/icon-field";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { chatPartnerHref } from "@/features/assistants/assistants";
import { PublishDialog } from "@/features/assistants/publish-dialog";
import { useSpace } from "@/features/spaces/use-space";
import { GroupChatAssistantList } from "./assistant-list";
import {
  groupChatQueryOptions,
  useUpdateGroupChat,
  type GroupChat,
  type GroupChatAssistant
} from "./use-group-chat";

function GeneralSection({ groupChat }: { groupChat: GroupChat }) {
  const t = useTranslations();
  const update = useUpdateGroupChat(groupChat.id);

  const name = useAutosaveField({
    key: "general",
    value: groupChat.name,
    save: (value) => update.mutateAsync({ name: value }),
    normalize: (value) => value.trim()
  });

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow
        title={t("name")}
        description={t("give_group_chat_name_displayed_to_users")}
        htmlFor="group-chat-name"
      >
        <Input
          id="group-chat-name"
          value={name.value}
          onChange={(event) => name.setValue(event.target.value)}
          // A group chat must keep a name — revert an emptied field on blur.
          onBlur={() => (name.value.trim() ? name.commit() : name.reset())}
        />
      </SettingsRow>
      <SettingsRow title={t("avatar")} description={t("avatar_description")}>
        <IconField
          iconId={groupChat.icon_id}
          onSave={(iconId) => update.mutateAsync({ icon_id: iconId })}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}

function AssistantsSection({ groupChat }: { groupChat: GroupChat }) {
  const t = useTranslations();
  const update = useUpdateGroupChat(groupChat.id);
  const autosave = useAutosave("assistants");
  const saved = useMemo(() => groupChat.tools.assistants, [groupChat.tools.assistants]);
  const [selected, setSelected] = useState<GroupChatAssistant[]>(saved);

  // Adopt server changes (our own save landing) unless the user diverged.
  const savedKey = JSON.stringify(saved);
  const savedRef = useRef(savedKey);
  useEffect(() => {
    if (savedRef.current === savedKey) return;
    const previous = savedRef.current;
    savedRef.current = savedKey;
    setSelected((current) => (JSON.stringify(current) === previous ? saved : current));
  }, [savedKey, saved]);

  function handleChange(next: GroupChatAssistant[]) {
    setSelected(next);
    void autosave(() =>
      update.mutateAsync({
        tools: {
          assistants: next.map((assistant) => ({
            id: assistant.id,
            user_description: assistant.user_description
          }))
        }
      })
    );
  }

  return (
    <SettingsGroup title={t("group_settings")}>
      <SettingsRow
        title={t("assistants")}
        description={t("assistants_will_be_able_to_answer_questions")}
      >
        <GroupChatAssistantList selected={selected} onChange={handleChange} />
      </SettingsRow>
    </SettingsGroup>
  );
}

function AdvancedSection({ groupChat }: { groupChat: GroupChat }) {
  const t = useTranslations();
  const update = useUpdateGroupChat(groupChat.id);
  const autosave = useAutosave("advanced");

  return (
    <SettingsGroup title={t("advanced_settings")}>
      <SettingsRow
        title={t("mentions")}
        description={t("allow_users_to_select_assistant_by_mentioning")}
      >
        <Label className="flex items-center justify-between gap-2 py-1 font-normal">
          {t("enable_mentions")}
          <Switch
            checked={groupChat.allow_mentions}
            disabled={update.isPending}
            onCheckedChange={(checked) =>
              autosave(() => update.mutateAsync({ allow_mentions: checked }))
            }
          />
        </Label>
      </SettingsRow>
      <SettingsRow
        title={t("response_labels")}
        description={t("show_answering_assistant_name_next_to_response")}
      >
        <Label className="flex items-center justify-between gap-2 py-1 font-normal">
          {t("show_labels")}
          <Switch
            checked={groupChat.show_response_label}
            disabled={update.isPending}
            onCheckedChange={(checked) =>
              autosave(() => update.mutateAsync({ show_response_label: checked }))
            }
          />
        </Label>
      </SettingsRow>
    </SettingsGroup>
  );
}

function PublishingSection({ groupChat }: { groupChat: GroupChat }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const update = useUpdateGroupChat(groupChat.id);
  const autosave = useAutosave("publishing");
  const [showDialog, setShowDialog] = useState(false);

  const permissions = groupChat.permissions ?? [];
  const canPublish = permissions.includes("publish");
  const canToggleInsights = permissions.includes("insight_toggle");

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/group-chats/{id}/publish/", {
          params: { path: { id: groupChat.id }, query: { published: !groupChat.published } }
        })
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(["group-chats", groupChat.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setShowDialog(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!canPublish && !canToggleInsights) return null;

  return (
    <SettingsGroup title={t("publishing")}>
      {canPublish && (
        <SettingsRow title={t("status")} description={t("publishing_group_chat_description")}>
          <div className="flex items-center gap-3">
            <Badge variant={groupChat.published ? "default" : "outline"}>
              {groupChat.published ? t("published") : t("draft")}
            </Badge>
            <Button
              variant={groupChat.published ? "destructive" : "default"}
              size="sm"
              onClick={() => setShowDialog(true)}
            >
              {groupChat.published ? t("unpublish") : t("publish")}
            </Button>
          </div>
          <PublishDialog
            open={showDialog}
            onOpenChange={setShowDialog}
            name={groupChat.name}
            published={groupChat.published}
            pending={publish.isPending}
            onConfirm={() => publish.mutate()}
          />
        </SettingsRow>
      )}
      {canToggleInsights && (
        <SettingsRow
          title={t("insights")}
          description={t("collect_insights_about_group_chat_usage")}
        >
          <Label className="flex items-center justify-between gap-2 py-1 font-normal">
            {t("enable_insights")}
            <Switch
              checked={groupChat.insight_enabled}
              disabled={update.isPending}
              onCheckedChange={(checked) =>
                autosave(() => update.mutateAsync({ insight_enabled: checked }))
              }
            />
          </Label>
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}

export function GroupChatEditor({ groupChatId }: { groupChatId: string }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { data: groupChat } = useSuspenseQuery(groupChatQueryOptions(browserApi, groupChatId));

  return (
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Link
            href={`/spaces/${routeId}/assistants`}
            className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
          >
            <ChevronLeft className="size-4" />
            {t("assistants")}
          </Link>
          <PageHeader title={groupChat.name}>
            <SaveStatusIndicator />
            <Button asChild variant="outline">
              <Link href={chatPartnerHref(routeId, { type: "group-chat", id: groupChat.id })}>
                {t("done")}
              </Link>
            </Button>
          </PageHeader>
        </div>
        <GeneralSection groupChat={groupChat} />
        <AssistantsSection groupChat={groupChat} />
        <AdvancedSection groupChat={groupChat} />
        <PublishingSection groupChat={groupChat} />
        <div className="min-h-12" />
      </div>
    </SaveStatusProvider>
  );
}
