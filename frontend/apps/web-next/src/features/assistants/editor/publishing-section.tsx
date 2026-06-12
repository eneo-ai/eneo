"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "../publish-dialog";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

function PublishStatusRow({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const [showDialog, setShowDialog] = useState(false);
  const published = assistant.published ?? false;

  const publish = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/assistants/{id}/publish/", {
          params: { path: { id: assistant.id }, query: { published: !published } }
        })
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(["assistants", assistant.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setShowDialog(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsRow title={t("status")} description={t("publishing_description")}>
      <div className="flex items-center gap-3">
        <Badge variant={published ? "default" : "outline"}>
          {published ? t("published") : t("draft")}
        </Badge>
        <Button
          variant={published ? "destructive" : "default"}
          size="sm"
          onClick={() => setShowDialog(true)}
        >
          {published ? t("unpublish") : t("publish")}
        </Button>
      </div>
      <PublishDialog
        open={showDialog}
        onOpenChange={setShowDialog}
        name={assistant.name}
        published={published}
        pending={publish.isPending}
        publishHint={t("api_keys_notifications_publish_assistant_hint")}
        onConfirm={() => publish.mutate()}
      />
    </SettingsRow>
  );
}

export function PublishingSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);

  const permissions = assistant.permissions ?? [];
  const canPublish = permissions.includes("publish");
  const canToggleInsights = permissions.includes("insight_toggle");
  if (!canPublish && !canToggleInsights) return null;

  return (
    <SettingsGroup title={t("publishing")}>
      {canPublish && <PublishStatusRow assistant={assistant} />}
      <SettingsRow title={t("insights")} description={t("insights_description")}>
        <Label
          className="flex items-center justify-between gap-2 py-1 font-normal"
          title={canToggleInsights ? undefined : t("only_space_admins_toggle")}
        >
          {t("enable_insights")}
          <Switch
            checked={assistant.insight_enabled}
            disabled={!canToggleInsights || update.isPending}
            onCheckedChange={(checked) => update.mutate({ insight_enabled: checked })}
          />
        </Label>
      </SettingsRow>
    </SettingsGroup>
  );
}
