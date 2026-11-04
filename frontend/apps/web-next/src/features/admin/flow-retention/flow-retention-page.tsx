import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsSection } from "@/features/admin/flow-settings/flow-settings-fields";
import {
  retentionDaysValid,
  retentionDraft,
  RetentionFields,
  type RetentionDraft
} from "@/features/flows/flow-retention";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";

type PolicySettings = Schema<"FlowRunRetentionPolicySettings">;
type Windows = Schema<"FlowRetentionPolicyPublic">;

const keys = {
  organization: ["flow-retention", "organization"] as const,
  spaces: ["flow-retention", "spaces"] as const,
  space: (spaceId: string) => ["flow-retention", "space", spaceId] as const,
  windows: ["flow-retention", "windows"] as const
};

/** Every space an administrator can set, however many pages the list takes. */
async function listSpaces(signal: AbortSignal) {
  const spaces: Schema<"FlowRunRetentionSpaceTarget">[] = [];
  for (;;) {
    const page = await unwrap(
      browserApi.GET("/api/v1/settings/flow-run-retention-policy/targets/spaces", {
        params: { query: { limit: 200, offset: spaces.length } },
        signal
      })
    );
    spaces.push(...page.items);
    if (!page.has_more) return spaces;
  }
}

function policyOf(draft: RetentionDraft) {
  return draft.own ? { days: draft.days!, mode: draft.mode } : null;
}

/**
 * The tenant's retention, which is not one of the flow settings: run history has its
 * own levels and permission, and every level saves on its own. A flow's own period is
 * set on the flow. Saving makes data eligible at most; a purge is a separate act.
 */
export function FlowRetentionPage() {
  const t = useTranslations();
  const { can } = useAppContext();
  const manages = can("retention_manage");
  return (
    <div className="flex w-full max-w-4xl flex-col gap-6">
      <PageHeader
        title={t("flow_retention_admin_title")}
        description={t("flow_retention_admin_description")}
      />
      {manages ? null : (
        <Banner status="info" title={t("flow_retention_admin_read_only")} collapsible={false} />
      )}
      <OrganizationSection manages={manages} />
      <SpaceSection manages={manages} />
      <WindowsSection />
    </div>
  );
}

function OrganizationSection({ manages }: { manages: boolean }) {
  const t = useTranslations();
  const policy = useQuery({
    queryKey: keys.organization,
    queryFn: ({ signal }) =>
      unwrap(browserApi.GET("/api/v1/settings/flow-run-retention-policy", { signal }))
  });
  return (
    <SettingsSection
      id="flow-retention-organization"
      title={t("flow_retention_admin_org_heading")}
      description={t("flow_retention_admin_org_description")}
    >
      <QueryStateBoundary query={policy} rows={2}>
        {(settings) => (
          <PolicyForm
            settings={settings}
            manages={manages}
            noneLabel={t("flow_retention_admin_org_none")}
            noneDescription={t("flow_retention_admin_org_none_hint")}
            ownLabel={t("flow_retention_admin_org_own")}
            queryKey={keys.organization}
            save={(body) =>
              unwrap(browserApi.PUT("/api/v1/settings/flow-run-retention-policy", { body }))
            }
          />
        )}
      </QueryStateBoundary>
    </SettingsSection>
  );
}

function SpaceSection({ manages }: { manages: boolean }) {
  const t = useTranslations();
  const [spaceId, setSpaceId] = useState("");
  const spaces = useQuery({
    queryKey: keys.spaces,
    queryFn: ({ signal }) => listSpaces(signal)
  });
  return (
    <SettingsSection
      id="flow-retention-spaces"
      title={t("flow_retention_admin_space_heading")}
      description={t("flow_retention_admin_space_description")}
    >
      <QueryStateBoundary query={spaces} rows={1}>
        {(items) =>
          items.length === 0 ? (
            <p className="text-ax-text-secondary m-0 text-sm">
              {t("flow_retention_admin_space_none")}
            </p>
          ) : (
            <div className="flex max-w-xl flex-col gap-4">
              <Selector
                label={t("flow_retention_admin_space_label")}
                placeholder={t("flow_retention_admin_space_placeholder")}
                value={spaceId}
                onChange={setSpaceId}
                options={items.map((space) => ({ value: space.id, label: space.name }))}
              />
              {spaceId ? <SpacePolicy spaceId={spaceId} manages={manages} /> : null}
            </div>
          )
        }
      </QueryStateBoundary>
    </SettingsSection>
  );
}

function SpacePolicy({ spaceId, manages }: { spaceId: string; manages: boolean }) {
  const t = useTranslations();
  const policy = useQuery({
    queryKey: keys.space(spaceId),
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/settings/flow-run-retention-policy/spaces/{space_id}", {
          params: { path: { space_id: spaceId } },
          signal
        })
      )
  });
  if (policy.isError) {
    return (
      <ListError
        error={policy.error}
        title={t("flow_retention_admin_load_failed")}
        onRetry={() => void policy.refetch()}
        isRetrying={policy.isFetching}
      />
    );
  }
  if (!policy.data)
    return <LoadingState rows={2} label={t("flow_retention_admin_space_heading")} />;
  const inherited = policy.data.inherited_policy;
  return (
    <PolicyForm
      key={spaceId}
      settings={policy.data}
      manages={manages}
      noneLabel={t("flows_retention_inherit")}
      noneDescription={
        inherited
          ? t("flow_retention_admin_inherit_org", { days: inherited.days })
          : t("flow_retention_admin_inherit_none")
      }
      ownLabel={t("flow_retention_admin_space_own")}
      queryKey={keys.space(spaceId)}
      save={(body) =>
        unwrap(
          browserApi.PUT("/api/v1/settings/flow-run-retention-policy/spaces/{space_id}", {
            params: { path: { space_id: spaceId } },
            body
          })
        )
      }
    />
  );
}

/** One level's policy with its own save; someone who may only read gets it disabled. */
function PolicyForm({
  settings,
  manages,
  noneLabel,
  noneDescription,
  ownLabel,
  queryKey,
  save
}: {
  settings: PolicySettings;
  manages: boolean;
  noneLabel: string;
  noneDescription: string;
  ownLabel: string;
  queryKey: readonly unknown[];
  save: (body: Schema<"FlowRunRetentionPolicyReplaceRequest">) => Promise<PolicySettings>;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => retentionDraft(settings));
  const [refused, setRefused] = useState(false);
  const mutation = useMutation({
    mutationFn: () => save({ policy: policyOf(draft) }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKey, saved);
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
        if (mutation.isPending) return;
        if (!draft.own || retentionDaysValid(draft.days)) mutation.mutate();
        else setRefused(true);
      }}
    >
      <RetentionFields
        draft={draft}
        onChange={setDraft}
        refused={refused}
        noneLabel={noneLabel}
        noneDescription={noneDescription}
        ownLabel={ownLabel}
        isDisabled={!manages}
      />
      {manages ? (
        <div>
          <Button
            type="submit"
            variant="primary"
            label={t("flows_settings_save")}
            isLoading={mutation.isPending}
            isInterruptible
          />
        </div>
      ) : null}
    </form>
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
