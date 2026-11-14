import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";
import { PublishDialog } from "../publish-dialog";
import { useUpdateAssistant, type Assistant } from "./use-assistant";
import { invalidateExpiringApiKeys } from "@/features/api-keys/api-keys";

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
      void invalidateExpiringApiKeys(queryClient);
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

/**
 * What other systems are told about the assistant, apart from the description
 * its own users read. Empty, they get that description.
 */
function ExternalClientsDescriptionRow({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const text = useAutosaveField({
    key: "assistant-external-clients-description",
    value: assistant.external_clients_description ?? "",
    save: (value) => update.mutateAsync({ external_clients_description: value })
  });

  return (
    <SettingsRow
      title={t("external_clients_hint_title")}
      description={t("external_clients_hint_description")}
      htmlFor="assistant-external-clients-description"
    >
      <Textarea
        id="assistant-external-clients-description"
        value={text.value}
        rows={3}
        maxLength={400}
        onChange={(event) => text.setValue(event.target.value)}
        onBlur={() => text.commit()}
      />
    </SettingsRow>
  );
}

export function PublishingSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("publishing");

  const permissions = assistant.permissions ?? [];
  const canPublish = permissions.includes("publish");
  const canToggleInsights = permissions.includes("insight_toggle");
  if (!canPublish && !canToggleInsights) return null;

  return (
    <SettingsGroup title={t("publishing")}>
      {canPublish && <PublishStatusRow assistant={assistant} />}
      <SettingsRow
        title={t("insights")}
        description={
          // Why the switch is off is written out: a title attribute is not shown on touch.
          canToggleInsights
            ? t("insights_description")
            : `${t("insights_description")} ${t("only_space_admins_toggle")}`
        }
      >
        <Label className="flex items-center justify-between gap-2 py-1 font-normal">
          {t("enable_insights")}
          {/* Saving, it stays enabled so it keeps focus; a toggle meanwhile is ignored. */}
          <Switch
            checked={assistant.insight_enabled}
            disabled={!canToggleInsights}
            aria-busy={update.isPending || undefined}
            onCheckedChange={(checked) => {
              if (!update.isPending)
                void autosave(() => update.mutateAsync({ insight_enabled: checked }));
            }}
          />
        </Label>
      </SettingsRow>
      {/* A Help Assistant is never asked from another client; the API refuses the change. */}
      {!assistant.is_help_assistant && (
        <SettingsRow
          title={t("external_clients")}
          description={
            // The right to decide this is the space admin's, as for insights.
            canToggleInsights
              ? t("external_clients_description")
              : `${t("external_clients_description")} ${t("only_space_admins_external_clients")}`
          }
        >
          <Label className="flex items-center justify-between gap-2 py-1 font-normal">
            {t("enable_external_clients")}
            <Switch
              checked={assistant.external_clients_enabled ?? false}
              disabled={!canToggleInsights}
              aria-busy={update.isPending || undefined}
              onCheckedChange={(checked) => {
                if (!update.isPending)
                  void autosave(() => update.mutateAsync({ external_clients_enabled: checked }));
              }}
            />
          </Label>
        </SettingsRow>
      )}
      {!assistant.is_help_assistant && assistant.external_clients_enabled && (
        <ExternalClientsDescriptionRow assistant={assistant} />
      )}
    </SettingsGroup>
  );
}
