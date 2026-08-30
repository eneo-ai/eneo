<script lang="ts">
  import type {
    FlowRunRetentionFlowTarget,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionReviewPage,
    FlowRunRetentionSpaceTarget,
    FlowRunRetentionSpaceTargetPage
  } from "@eneo/eneo-js";
  import ShieldCheck from "lucide-svelte/icons/shield-check";
  import { untrack } from "svelte";

  import { Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  import FlowRunRetentionScopeEditor from "./FlowRunRetentionScopeEditor.svelte";

  type Props = {
    initialPolicy: FlowRunRetentionPolicySettings;
    initialReviewQueue: FlowRunRetentionReviewPage | null;
    initialSpaceTargets: FlowRunRetentionSpaceTargetPage;
    onDirtyChange?: (dirty: boolean) => void;
  };

  let { initialPolicy, initialReviewQueue, initialSpaceTargets, onDirtyChange }: Props = $props();
  const eneo = getEneo();
  const PAGE_SIZE = 50;
  const TARGET_PAGE_SIZE = 200;

  const emptyReviewQueue: FlowRunRetentionReviewPage = {
    items: [],
    count: 0,
    has_more: false,
    next_cursor: null
  };
  let organizationPolicy = $state(untrack(() => initialPolicy));
  let reviewQueue = $state(untrack(() => initialReviewQueue ?? emptyReviewQueue));
  let reviewUnavailable = $state(untrack(() => initialReviewQueue === null));
  let reviewPageIndex = $state(0);
  let reviewCursor = $state<string | undefined>();
  let reviewCursorHistory = $state<Array<string | undefined>>([]);
  let reviewRetryCursor = $state<string | undefined>();
  let reviewRetryPageIndex = $state(0);
  let reviewRetryCursorHistory = $state<Array<string | undefined>>([]);
  let reviewLoading = $state(false);

  let spaces = $state(
    untrack(() => [...initialSpaceTargets.items] as FlowRunRetentionSpaceTarget[])
  );
  let spacesHaveMore = $state(untrack(() => initialSpaceTargets.has_more));
  let spaceTargetOffset = $state(untrack(() => initialSpaceTargets.items.length));
  let spaceTargetsLoading = $state(false);
  let selectedSpaceId = $state<string | undefined>();
  let selectedFlowId = $state<string | undefined>();
  let spacePolicy = $state<FlowRunRetentionPolicySettings | null>(null);
  let flowPolicy = $state<FlowRunRetentionPolicySettings | null>(null);
  let flows = $state<FlowRunRetentionFlowTarget[]>([]);
  let flowsHaveMore = $state(false);
  let flowTargetOffset = $state(0);
  let flowTargetsLoading = $state(false);
  let scopeLoading = $state(false);
  let organizationPolicyDirty = $state(false);
  let spacePolicyDirty = $state(false);
  let flowPolicyDirty = $state(false);

  $effect(() => {
    onDirtyChange?.(organizationPolicyDirty || spacePolicyDirty || flowPolicyDirty);
    return () => onDirtyChange?.(false);
  });

  const sortedSpaces = $derived(
    [...spaces].sort((left, right) => left.name.localeCompare(right.name))
  );
  const sortedFlows = $derived(
    [...flows].sort((left, right) => left.name.localeCompare(right.name))
  );
  const dateFormatter = new Intl.DateTimeFormat(getLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });

  function selectedSpaceName(): string {
    return sortedSpaces.find((space) => space.id === selectedSpaceId)?.name ?? "";
  }

  function selectedFlowName(): string {
    return sortedFlows.find((flow) => flow.id === selectedFlowId)?.name ?? "";
  }

  function formatDate(value: string): string {
    return dateFormatter.format(new Date(value));
  }

  function policyModeLabel(mode: "preserve" | "review_required"): string {
    return mode === "preserve"
      ? m.flow_run_retention_mode_preserve()
      : m.flow_run_retention_mode_review();
  }

  function sourceLabel(source: "organization" | "space" | "flow"): string {
    if (source === "organization") return m.flow_run_retention_scope_organization();
    if (source === "space") return m.flow_run_retention_scope_space();
    return m.flow_run_retention_scope_flow();
  }

  async function saveOrganizationPolicy(
    policy: FlowRunRetentionPolicy | null
  ): Promise<FlowRunRetentionPolicySettings> {
    const updated = await eneo.settings.replaceOrganizationFlowRunRetentionPolicy({ policy });
    organizationPolicy = updated;
    await refreshSelectedPolicyProjections();
    await loadReviewPage(undefined, 0, []);
    return updated;
  }

  async function saveSpacePolicy(
    policy: FlowRunRetentionPolicy | null
  ): Promise<FlowRunRetentionPolicySettings> {
    if (!selectedSpaceId) throw new Error("A Space must be selected before saving retention.");
    const savedSpaceId = selectedSpaceId;
    const updated = await eneo.settings.replaceSpaceFlowRunRetentionPolicy({
      spaceId: savedSpaceId,
      policy
    });
    if (selectedSpaceId === savedSpaceId) {
      spacePolicy = updated;
      await refreshSelectedFlowProjection();
    }
    await loadReviewPage(undefined, 0, []);
    return updated;
  }

  async function saveFlowPolicy(
    policy: FlowRunRetentionPolicy | null
  ): Promise<FlowRunRetentionPolicySettings> {
    if (!selectedFlowId) throw new Error("A Flow must be selected before saving retention.");
    const savedFlowId = selectedFlowId;
    const updated = await eneo.settings.replaceFlowRunRetentionPolicy({
      flowId: savedFlowId,
      policy
    });
    if (selectedFlowId === savedFlowId) flowPolicy = updated;
    await loadReviewPage(undefined, 0, []);
    return updated;
  }

  async function refreshSelectedPolicyProjections(): Promise<void> {
    const spaceId = selectedSpaceId;
    if (spaceId) {
      try {
        const refreshed = await eneo.settings.getSpaceFlowRunRetentionPolicy({ spaceId });
        if (selectedSpaceId === spaceId) spacePolicy = refreshed;
      } catch (error) {
        toastError(error);
      }
    }
    await refreshSelectedFlowProjection();
  }

  async function refreshSelectedFlowProjection(): Promise<void> {
    const flowId = selectedFlowId;
    if (!flowId) return;
    try {
      const refreshed = await eneo.settings.getFlowRunRetentionPolicy({ flowId });
      if (selectedFlowId === flowId) flowPolicy = refreshed;
    } catch (error) {
      toastError(error);
    }
  }

  function confirmDiscardScopeChanges(): boolean {
    return !(spacePolicyDirty || flowPolicyDirty) || confirm(m.flow_settings_leave_confirm());
  }

  function chooseSpace(value: string | undefined): void {
    if (value === selectedSpaceId || !confirmDiscardScopeChanges()) return;
    selectedSpaceId = value;
    selectedFlowId = undefined;
    spacePolicy = null;
    flowPolicy = null;
    flows = [];
    flowsHaveMore = false;
    flowTargetOffset = 0;
    if (!value) return;
    void loadSpace(value);
  }

  async function loadSpace(spaceId: string): Promise<void> {
    scopeLoading = true;
    try {
      const [policy, flowTargets] = await Promise.all([
        eneo.settings.getSpaceFlowRunRetentionPolicy({ spaceId }),
        eneo.settings.listFlowRunRetentionFlowTargets({
          spaceId,
          limit: TARGET_PAGE_SIZE,
          offset: 0
        })
      ]);
      if (selectedSpaceId !== spaceId) return;
      spacePolicy = policy;
      flows = flowTargets.items;
      flowsHaveMore = flowTargets.has_more;
      flowTargetOffset = flowTargets.items.length;
    } catch (error) {
      if (selectedSpaceId === spaceId) toastError(error);
    } finally {
      if (selectedSpaceId === spaceId) scopeLoading = false;
    }
  }

  async function loadMoreSpaces(): Promise<void> {
    if (!spacesHaveMore || spaceTargetsLoading) return;
    spaceTargetsLoading = true;
    try {
      const page = await eneo.settings.listFlowRunRetentionSpaceTargets({
        limit: TARGET_PAGE_SIZE,
        offset: spaceTargetOffset
      });
      const loadedIds = new Set(spaces.map((space) => space.id));
      spaces = [...spaces, ...page.items.filter((space) => !loadedIds.has(space.id))];
      spaceTargetOffset += page.items.length;
      spacesHaveMore = page.has_more;
    } catch (error) {
      toastError(error);
    } finally {
      spaceTargetsLoading = false;
    }
  }

  async function loadMoreFlows(): Promise<void> {
    const spaceId = selectedSpaceId;
    if (!spaceId || !flowsHaveMore || flowTargetsLoading) return;
    flowTargetsLoading = true;
    try {
      const page = await eneo.settings.listFlowRunRetentionFlowTargets({
        spaceId,
        limit: TARGET_PAGE_SIZE,
        offset: flowTargetOffset
      });
      if (selectedSpaceId !== spaceId) return;
      const loadedIds = new Set(flows.map((flow) => flow.id));
      flows = [...flows, ...page.items.filter((flow) => !loadedIds.has(flow.id))];
      flowTargetOffset += page.items.length;
      flowsHaveMore = page.has_more;
    } catch (error) {
      if (selectedSpaceId === spaceId) toastError(error);
    } finally {
      flowTargetsLoading = false;
    }
  }

  function chooseFlow(value: string | undefined): void {
    if (
      value === selectedFlowId ||
      (flowPolicyDirty && !confirm(m.flow_settings_leave_confirm()))
    ) {
      return;
    }
    selectedFlowId = value;
    flowPolicy = null;
    if (!value) return;
    void loadFlow(value);
  }

  async function loadFlow(flowId: string): Promise<void> {
    scopeLoading = true;
    try {
      const policy = await eneo.settings.getFlowRunRetentionPolicy({ flowId });
      if (selectedFlowId === flowId) flowPolicy = policy;
    } catch (error) {
      if (selectedFlowId === flowId) toastError(error);
    } finally {
      if (selectedFlowId === flowId) scopeLoading = false;
    }
  }

  async function loadReviewPage(
    cursor: string | undefined,
    pageIndex: number,
    cursorHistory: Array<string | undefined>
  ): Promise<void> {
    if (reviewLoading || pageIndex < 0) return;
    reviewLoading = true;
    reviewRetryCursor = cursor;
    reviewRetryPageIndex = pageIndex;
    reviewRetryCursorHistory = cursorHistory;
    try {
      reviewQueue = await eneo.settings.listOrganizationFlowRunRetentionReviewQueue({
        limit: PAGE_SIZE,
        cursor
      });
      reviewUnavailable = false;
      reviewCursor = cursor;
      reviewPageIndex = pageIndex;
      reviewCursorHistory = cursorHistory;
    } catch (error) {
      reviewUnavailable = true;
      toastError(error);
    } finally {
      reviewLoading = false;
    }
  }
</script>

<Settings.Page density="compact">
  <Settings.Group
    title={m.flow_run_retention_policy_group()}
    description={m.flow_run_retention_policy_group_description()}
    density="compact"
  >
    <Alert.Root class="mx-4 max-w-3xl lg:mx-0.5">
      <ShieldCheck aria-hidden="true" />
      <Alert.Title>{m.flow_run_retention_safe_title()}</Alert.Title>
      <Alert.Description>{m.flow_run_retention_safe_description()}</Alert.Description>
    </Alert.Root>

    <FlowRunRetentionScopeEditor
      settings={organizationPolicy}
      title={m.flow_run_retention_organization_title()}
      description={m.flow_run_retention_organization_description()}
      onSave={saveOrganizationPolicy}
      onDirtyChange={(dirty) => (organizationPolicyDirty = dirty)}
    />
  </Settings.Group>

  <Settings.Group
    title={m.flow_run_retention_overrides_group()}
    description={m.flow_run_retention_overrides_description()}
    density="compact"
  >
    <div class="mx-4 grid max-w-3xl gap-4 md:grid-cols-2 lg:mx-0.5">
      <Field.Field>
        <Field.Label for="flow-retention-space-select">
          {m.flow_run_retention_select_space()}
        </Field.Label>
        <Select.Root
          type="single"
          bind:value={() => selectedSpaceId, chooseSpace}
          disabled={scopeLoading}
        >
          <Select.Trigger
            id="flow-retention-space-select"
            class="w-full"
            aria-label={m.flow_run_retention_select_space()}
          >
            <span class="truncate">
              {selectedSpaceId
                ? selectedSpaceName()
                : m.flow_run_retention_select_space_placeholder()}
            </span>
          </Select.Trigger>
          <Select.Content>
            {#each sortedSpaces as space (space.id)}
              <Select.Item value={space.id} label={space.name}>{space.name}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
        <Field.Description>{m.flow_run_retention_select_space_description()}</Field.Description>
        {#if spacesHaveMore}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={spaceTargetsLoading}
            onclick={loadMoreSpaces}
          >
            {m.flow_run_retention_load_more_spaces()}
          </Button>
        {/if}
      </Field.Field>

      <Field.Field>
        <Field.Label for="flow-retention-flow-select">
          {m.flow_run_retention_select_flow()}
        </Field.Label>
        <Select.Root
          type="single"
          bind:value={() => selectedFlowId, chooseFlow}
          disabled={!selectedSpaceId || scopeLoading || sortedFlows.length === 0}
        >
          <Select.Trigger
            id="flow-retention-flow-select"
            class="w-full"
            aria-label={m.flow_run_retention_select_flow()}
          >
            <span class="truncate">
              {selectedFlowId ? selectedFlowName() : m.flow_run_retention_select_flow_placeholder()}
            </span>
          </Select.Trigger>
          <Select.Content>
            {#each sortedFlows as flow (flow.id)}
              <Select.Item value={flow.id} label={flow.name}>{flow.name}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
        <Field.Description>
          {selectedSpaceId && sortedFlows.length === 0 && !scopeLoading
            ? m.flow_run_retention_space_has_no_flows()
            : m.flow_run_retention_select_flow_description()}
        </Field.Description>
        {#if selectedSpaceId && flowsHaveMore}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={flowTargetsLoading}
            onclick={loadMoreFlows}
          >
            {m.flow_run_retention_load_more_flows()}
          </Button>
        {/if}
      </Field.Field>
    </div>

    {#if spacePolicy && selectedSpaceId}
      {#key `space-${selectedSpaceId}`}
        <FlowRunRetentionScopeEditor
          settings={spacePolicy}
          title={m.flow_run_retention_space_title({ space: selectedSpaceName() })}
          description={m.flow_run_retention_space_description()}
          onSave={saveSpacePolicy}
          onDirtyChange={(dirty) => (spacePolicyDirty = dirty)}
        />
      {/key}
    {/if}

    {#if flowPolicy && selectedFlowId}
      {#key `flow-${selectedFlowId}`}
        <FlowRunRetentionScopeEditor
          settings={flowPolicy}
          title={m.flow_run_retention_flow_title({ flow: selectedFlowName() })}
          description={m.flow_run_retention_flow_description()}
          onSave={saveFlowPolicy}
          onDirtyChange={(dirty) => (flowPolicyDirty = dirty)}
        />
      {/key}
    {/if}
  </Settings.Group>

  <Settings.Group
    title={m.flow_run_retention_review_queue_title()}
    description={m.flow_run_retention_review_queue_description()}
    density="compact"
  >
    <div class="mx-4 space-y-3 lg:mx-0.5">
      {#if reviewUnavailable}
        <Alert.Root>
          <Alert.Title>{m.flow_run_retention_review_queue_unavailable_title()}</Alert.Title>
          <Alert.Description>
            {m.flow_run_retention_review_queue_unavailable_description()}
          </Alert.Description>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={reviewLoading}
            onclick={() =>
              loadReviewPage(reviewRetryCursor, reviewRetryPageIndex, reviewRetryCursorHistory)}
          >
            {m.flow_run_retention_review_queue_refresh()}
          </Button>
        </Alert.Root>
      {:else}
        <div class="flex flex-wrap items-center justify-between gap-3">
          <Badge variant="secondary">
            {m.flow_run_retention_review_queue_count({ count: reviewQueue.count })}
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={reviewLoading}
            onclick={() => loadReviewPage(reviewCursor, reviewPageIndex, reviewCursorHistory)}
          >
            {m.flow_run_retention_review_queue_refresh()}
          </Button>
        </div>

        {#if reviewQueue.items.length === 0}
          <div class="border-default bg-secondary rounded-md border p-4">
            <p class="text-primary text-sm font-medium">
              {m.flow_run_retention_review_queue_empty_title()}
            </p>
            <p class="text-secondary mt-1 text-sm">
              {m.flow_run_retention_review_queue_empty_description()}
            </p>
          </div>
        {:else}
          <div class="border-default overflow-x-auto rounded-md border">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head>{m.flow_run_retention_review_flow()}</Table.Head>
                  <Table.Head>{m.flow_run_retention_review_space()}</Table.Head>
                  <Table.Head>{m.flow_run_retention_review_eligible_since()}</Table.Head>
                  <Table.Head>{m.flow_run_retention_review_policy()}</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#each reviewQueue.items as item (item.run_id)}
                  <Table.Row>
                    <Table.Cell>
                      <div class="min-w-44">
                        <p class="text-primary font-medium">{item.flow_name}</p>
                        <p class="text-secondary font-mono text-xs">{item.run_id}</p>
                      </div>
                    </Table.Cell>
                    <Table.Cell>{item.space_name}</Table.Cell>
                    <Table.Cell class="whitespace-nowrap tabular-nums">
                      {formatDate(item.eligible_since)}
                    </Table.Cell>
                    <Table.Cell>
                      <div class="min-w-40 text-sm">
                        <p class="text-primary">
                          {item.effective_policy.days}
                          {m.flow_retention_days_suffix()} ·
                          {policyModeLabel(item.effective_policy.mode)}
                        </p>
                        <p class="text-secondary text-xs">
                          {m.flow_run_retention_review_inherited_from({
                            source: sourceLabel(item.policy_source)
                          })}
                        </p>
                      </div>
                    </Table.Cell>
                  </Table.Row>
                {/each}
              </Table.Body>
            </Table.Root>
          </div>
        {/if}

        <div class="flex items-center justify-between gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={reviewLoading || reviewPageIndex === 0}
            onclick={() =>
              loadReviewPage(
                reviewCursorHistory.at(-1),
                Math.max(0, reviewPageIndex - 1),
                reviewCursorHistory.slice(0, -1)
              )}
          >
            {m.previous()}
          </Button>
          <span class="text-secondary text-xs">
            {m.flow_run_retention_review_queue_page({
              from: reviewQueue.count === 0 ? 0 : reviewPageIndex * PAGE_SIZE + 1,
              to: reviewPageIndex * PAGE_SIZE + reviewQueue.count
            })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={reviewLoading || !reviewQueue.next_cursor}
            onclick={() =>
              loadReviewPage(reviewQueue.next_cursor ?? undefined, reviewPageIndex + 1, [
                ...reviewCursorHistory,
                reviewCursor
              ])}
          >
            {m.next()}
          </Button>
        </div>
      {/if}

      <p class="text-secondary max-w-3xl text-xs leading-relaxed">
        {m.flow_run_retention_adjacent_data_note()}
      </p>
    </div>
  </Settings.Group>
</Settings.Page>
