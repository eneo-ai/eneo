import { Button } from "@astryxdesign/core/Button";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { SettingsSection } from "@/features/admin/flow-settings/flow-settings-fields";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";

type Windows = Schema<"FlowRetentionPolicyPublic">;

const keys = { windows: ["flow-retention", "windows"] as const };

/**
 * The organisation's windows for live text and debug evidence. Run history has no
 * setting here: each space's time caps its flows, set in the space, and a flow may
 * choose a shorter one. Saving removes nothing: the live-text window dates new live text,
 * which the explicit purge removes once expired, and the debug-evidence window is stored
 * but nothing uses it yet.
 */
export function FlowRetentionPage() {
  const t = useTranslations();
  return (
    <div className="flex w-full max-w-4xl flex-col gap-6">
      <PageHeader
        title={t("flow_retention_admin_title")}
        description={t("flow_retention_admin_description")}
      />
      <WindowsSection />
    </div>
  );
}

function WindowsSection() {
  const t = useTranslations();
  const policy = useQuery({
    queryKey: keys.windows,
    queryFn: ({ signal }) =>
      unwrap(browserApi.GET("/api/v1/settings/flow-retention-policy", { signal }))
  });
  return (
    <SettingsSection
      id="flow-retention-windows"
      title={t("flow_retention_admin_windows_heading")}
      description={t("flow_retention_admin_windows_description")}
    >
      <QueryStateBoundary query={policy} rows={2}>
        {(windows) => <WindowsForm windows={windows} />}
      </QueryStateBoundary>
    </SettingsSection>
  );
}

function WindowsForm({ windows }: { windows: Windows }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState(windows.flow_runtime_upload_abandonment_days);
  const [debug, setDebug] = useState(windows.run_debug_evidence_days);
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.PATCH("/api/v1/settings/flow-retention-policy", {
          body: { flow_runtime_upload_abandonment_days: uploads, run_debug_evidence_days: debug }
        })
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.windows, saved);
      toast.success(t("flows_retention_saved"));
    },
    onError: (error) => toastApiError(error, t)
  });
  return (
    <form
      noValidate
      className="flex max-w-xl flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!save.isPending) save.mutate();
      }}
    >
      <NumberInput
        label={t("flow_retention_admin_upload_label")}
        description={t("flow_retention_admin_upload_description")}
        value={uploads}
        onChange={setUploads}
        hasClear
        min={1}
        max={2555}
      />
      <NumberInput
        label={t("flow_retention_admin_debug_label")}
        description={t("flow_retention_admin_debug_description")}
        value={debug}
        onChange={setDebug}
        hasClear
        min={1}
        max={2555}
      />
      <div>
        <Button
          type="submit"
          variant="primary"
          label={t("flows_settings_save")}
          isLoading={save.isPending}
          isInterruptible
        />
      </div>
    </form>
  );
}
