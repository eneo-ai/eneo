<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { page } from "$app/stores";
  import { Table, Input, Button } from "@intric/ui";
  import { Page } from "$lib/components/layout";
  import SimpleTextCell from "$lib/components/layout/SimpleTextCell.svelte";
  import { Settings } from "$lib/components/layout";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { formatPercent } from "$lib/core/formatting/formatPercent";
  import { dynamicColour } from "$lib/core/colours";
  import { modelOrgs } from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { createRender } from "svelte-headless-table";
  import { CalendarDate } from "@internationalized/date";
  import {
    IntricError,
    type ModelUsage,
    type TokenUsageSummary,
    type UserTokenUsage
  } from "@intric/intric-js";

  const intric = getIntric();
  const userId = $page.params.userId;

  // Get date range from URL params or default to last 30 days
  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());
  let dateRange = $state({
    start: today.subtract({ days: 30 }),
    end: today
  });

  let user = $state<UserTokenUsage | null>(null);
  let modelBreakdown = $state<TokenUsageSummary | null>(null);
  let isLoadingUser = $state(false);
  let isLoadingBreakdown = $state(false);
  let userError = $state<string | null>(null);
  let breakdownError = $state<string | null>(null);

  // Load user data and model breakdown
  async function loadUserData() {
    if (!userId) return;

    isLoadingUser = true;
    userError = null;
    try {
      // Fetch single user data using the new endpoint
      const userSummary = await intric.usage.tokens.getUserSummary(userId, {
        startDate: dateRange.start.toString(),
        endDate: dateRange.end.add({ days: 1 }).toString()
      });

      user = userSummary.user;

      if (!user) {
        // User not found in current date range
        console.error("User not found in current date range");
        return;
      }
    } catch (error: unknown) {
      console.error("Failed to load user data:", error);
      userError = error instanceof IntricError ? error.message : "unknown error";
    } finally {
      isLoadingUser = false;
    }
  }

  async function loadModelBreakdown() {
    if (!userId) return;

    isLoadingBreakdown = true;
    breakdownError = null;
    try {
      modelBreakdown = await intric.usage.tokens.getUserModelBreakdown(userId, {
        startDate: dateRange.start.toString(),
        endDate: dateRange.end.add({ days: 1 }).toString()
      });
    } catch (error: unknown) {
      breakdownError = error instanceof IntricError ? error.message : "unknown error";
      console.error("Failed to load user model breakdown:", error);
    } finally {
      isLoadingBreakdown = false;
    }
  }

  // Load data when component mounts or date range changes
  $effect(() => {
    if (dateRange.start && dateRange.end) {
      loadUserData();
      loadModelBreakdown();
    }
  });

  // Group models by organization for better visualization
  const modelsByOrg = $derived.by(() => {
    if (!modelBreakdown?.models) return [];

    return Object.values(
      modelBreakdown.models.reduce(
        (acc, model) => {
          const org = model.model_org ?? "Unknown";
          if (!acc[org]) {
            acc[org] = {
              label: org || "Unknown Organization",
              tokenCount: 0,
              colour: modelOrgs[org]?.chartColour || "chart-blue",
              models: [],
              org: org
            };
          }
          acc[org].tokenCount += model.total_token_usage;
          acc[org].models.push(model);
          return acc;
        },
        {} as Record<
          string,
          {
            label: string;
            tokenCount: number;
            colour: string;
            models: ModelUsage[];
            org: string;
          }
        >
      )
    ).sort((a, b) => b.tokenCount - a.tokenCount);
  });

  // Create table for model breakdown
  const modelTable = Table.createWithResource<ModelUsage>([]);
  const modelTableViewModel = modelTable.createViewModel([
    modelTable.column({
      header: "Model",
      accessor: (model) => model,
      id: "model_name",
      cell: (item) => {
        return createRender(SimpleTextCell, {
          primary: item.value.model_nickname || item.value.model_name,
          secondary: item.value.model_org || "Unknown"
        });
      },
      plugins: {
        tableFilter: {
          getFilterValue(value) {
            return `${value.model_nickname || value.model_name} ${value.model_org || ""}`;
          }
        }
      }
    }),
    modelTable.column({
      header: "Requests",
      accessor: "request_count",
      id: "request_count",
      cell: (item) => formatNumber(item.value)
    }),
    modelTable.column({
      header: "Input Tokens",
      accessor: "input_token_usage",
      id: "input_tokens",
      cell: (item) => formatNumber(item.value, "compact", 1)
    }),
    modelTable.column({
      header: "Output Tokens",
      accessor: "output_token_usage",
      id: "output_tokens",
      cell: (item) => formatNumber(item.value, "compact", 1)
    }),
    modelTable.column({
      header: "Total Tokens",
      accessor: "total_token_usage",
      id: "total_tokens",
      cell: (item) => formatNumber(item.value, "compact", 1)
    })
  ]);

  // Update model table when data changes
  $effect(() => {
    if (modelBreakdown?.models) {
      modelTable.update(modelBreakdown.models);
    }
  });

  // Get usage intensity based on requests - using semantic classes
  function getUsageIntensity(requests: number) {
    if (requests > 100) return { label: "High Usage", class: "bg-secondary text-error" };
    if (requests > 20) return { label: "Medium Usage", class: "bg-secondary text-warning" };
    return { label: "Low Usage", class: "bg-secondary text-success" };
  }

  // Get top 5 models by token usage
  const topModels = $derived.by(() => {
    if (!modelBreakdown?.models) return [];
    return [...modelBreakdown.models]
      .sort((a, b) => b.total_token_usage - a.total_token_usage)
      .slice(0, 5);
  });
</script>

<svelte:head>
  <title>User Token Usage - {user?.username || "Loading..."}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title>
      <div class="flex items-center gap-2">
        <Button
          variant="simple"
          onclick={() => history.back()}
          class="text-muted hover:text-primary"
        >
          ← Usage
        </Button>
        <span class="text-muted">/</span>
        <h1 class="text-primary text-[1.45rem] font-extrabold">
          {user?.username || "Loading..."}
        </h1>
      </div>
    </Page.Title>

    <Page.Flex>
      <Input.DateRange bind:value={dateRange} />
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    {#if user}
      <!-- User Overview Statistics -->
      <Settings.Page>
        <Settings.Group title="Overview">
          <Settings.Row
            title="User Information"
            description="Profile and usage activity for {user.username}."
          >
            <div class="flex items-center gap-4">
              <!-- User Avatar using dynamic color system -->
              <div
                {...dynamicColour({ basedOn: user.email })}
                class="bg-dynamic-default flex h-16 w-16 items-center justify-center rounded-xl text-xl font-semibold text-white"
              >
                {user.username.slice(0, 1).toUpperCase()}
              </div>
              <div class="min-w-0 flex-1">
                <h3 class="text-primary truncate text-lg font-semibold">
                  {user.username}
                </h3>
                <p class="text-muted truncate text-sm">
                  {user.email}
                </p>
                <div class="mt-2">
                  <span
                    class="inline-flex items-center rounded-full px-3 py-1.5 text-sm font-medium {getUsageIntensity(
                      user.total_requests
                    ).class}"
                  >
                    {getUsageIntensity(user.total_requests).label}
                  </span>
                </div>
              </div>
            </div>
          </Settings.Row>

          <Settings.Row
            title="Token Usage Summary"
            description="Total tokens consumed by {user.username} in the selected period."
          >
            <div class="grid grid-cols-1 gap-4 md:grid-cols-4">
              <div class="text-center">
                <div class="text-primary text-2xl font-bold">
                  {formatNumber(user.total_tokens, "compact", 1)}
                </div>
                <div class="text-muted text-sm">Total Tokens</div>
              </div>
              <div class="text-center">
                <div class="text-success text-2xl font-bold">
                  {formatNumber(user.total_input_tokens, "compact", 1)}
                </div>
                <div class="text-muted text-sm">Input Tokens</div>
                <div class="text-muted mt-1 text-xs">
                  {formatPercent(user.total_input_tokens / user.total_tokens)} of total
                </div>
              </div>
              <div class="text-center">
                <div class="text-warning text-2xl font-bold">
                  {formatNumber(user.total_output_tokens, "compact", 1)}
                </div>
                <div class="text-muted text-sm">Output Tokens</div>
                <div class="text-muted mt-1 text-xs">
                  {formatPercent(user.total_output_tokens / user.total_tokens)} of total
                </div>
              </div>
              <div class="text-center">
                <div class="text-info text-2xl font-bold">
                  {formatNumber(user.total_requests)}
                </div>
                <div class="text-muted text-sm">Total Requests</div>
                <div class="text-muted mt-1 text-xs">
                  {formatNumber(user.total_tokens / Math.max(user.total_requests, 1), "compact", 1)}
                  tokens avg/request
                </div>
              </div>
            </div>
          </Settings.Row>

          {#if modelBreakdown && modelBreakdown.models && modelBreakdown.models.length > 0 && modelsByOrg.length > 0}
            <Settings.Row
              title="Usage by Organization"
              description="See how token usage is distributed across different AI model providers."
            >
              <div class="flex flex-col gap-4">
                <div class="bg-secondary flex h-4 w-full overflow-clip rounded-full">
                  {#each modelsByOrg.filter((org) => org.tokenCount > 0) as org (org.org)}
                    <div
                      class="last-of-type:!border-none"
                      style="width: {formatPercent(
                        org.tokenCount / user.total_tokens
                      )}; min-width: 1.5%; background: var(--{org.colour}); border-right: 3px solid var(--background-primary)"
                    ></div>
                  {/each}
                </div>
                <div class="flex flex-wrap gap-x-6">
                  {#each modelsByOrg as org (org.org)}
                    <div class="flex items-center gap-2">
                      <div
                        style="background: var(--{org.colour})"
                        class="border-stronger h-3 w-3 flex-shrink-0 rounded-full border"
                      ></div>
                      <p>
                        <span class="font-medium">{org.label}</span>: {formatNumber(
                          org.tokenCount,
                          "compact"
                        )} ({formatPercent(org.tokenCount / user.total_tokens)})
                      </p>
                    </div>
                  {/each}
                </div>
              </div>
            </Settings.Row>
          {/if}
        </Settings.Group>

        <Settings.Group title="Details">
          {#if isLoadingBreakdown}
            <Settings.Row title="Loading..." description="Loading detailed model breakdown...">
              <div class="text-muted flex items-center gap-2">
                <div class="h-4 w-4 animate-spin rounded-full border-b-2 border-current"></div>
                <span>Loading model breakdown...</span>
              </div>
            </Settings.Row>
          {:else if breakdownError}
            <Settings.Row
              title="Error Loading Model Breakdown"
              description="Failed to load model usage details."
            >
              <div class="text-center">
                <div class="text-red-500">{breakdownError}</div>
              </div>
            </Settings.Row>
          {:else if modelBreakdown && modelBreakdown.models && modelBreakdown.models.length > 0}
            <Settings.Row
              title="Top Models"
              description="Most frequently used AI models by this user."
            >
              <div class="space-y-4">
                {#each topModels as model (model.model_name)}
                  <div class="space-y-2">
                    <div class="flex items-center justify-between">
                      <div class="min-w-0 flex-1">
                        <p class="truncate text-sm font-medium">
                          {model.model_nickname || model.model_name}
                        </p>
                        <p class="text-muted text-xs">{model.model_org || "Unknown"}</p>
                      </div>
                      <div class="ml-4 flex-shrink-0 text-right">
                        <p class="text-sm font-medium">
                          {formatNumber(model.total_token_usage, "compact", 1)}
                        </p>
                        <p class="text-muted text-xs">
                          {formatNumber(model.request_count)} requests
                        </p>
                      </div>
                    </div>
                    <!-- Visual bar indicator using model org colors -->
                    <div class="bg-secondary h-2 overflow-hidden rounded-full">
                      <div
                        class="h-full rounded-full transition-all duration-300"
                        style="width: {Math.max(
                          2,
                          topModels.length > 0
                            ? (model.total_token_usage / topModels[0].total_token_usage) * 100
                            : 0
                        )}%; background: var(--{modelOrgs[model.model_org || 'Unknown']
                          ?.chartColour || 'chart-blue'})"
                      ></div>
                    </div>
                  </div>
                {/each}
              </div>
            </Settings.Row>

            <Settings.Row
              title="Complete Model Breakdown"
              description="Detailed usage statistics for all models used by this user."
              fullWidth
            >
              <Table.Root viewModel={modelTableViewModel} resourceName="model" displayAs="list" />
            </Settings.Row>
          {:else}
            <Settings.Row
              title="No Model Usage"
              description="This user has not used any AI models in the selected period."
            >
              <div class="py-8 text-center">
                <div
                  class="bg-secondary mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
                >
                  <svg
                    class="text-muted h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                    />
                  </svg>
                </div>
                <h3 class="text-primary mb-2 text-lg font-medium">No Model Usage</h3>
                <p class="text-muted">
                  This user has not used any AI models in the selected period.
                </p>
              </div>
            </Settings.Row>
          {/if}
        </Settings.Group>
      </Settings.Page>
    {:else if isLoadingUser}
      <div class="bg-secondary/30 border-default rounded-lg border p-8">
        <div class="text-muted flex items-center justify-center gap-2">
          <div class="h-4 w-4 animate-spin rounded-full border-b-2 border-current"></div>
          <span>Loading user information...</span>
        </div>
      </div>
    {:else if userError}
      <div class="bg-secondary/30 border-default rounded-lg border p-8">
        <div class="text-center">
          <div class="text-red-500">{userError}</div>
        </div>
      </div>
    {:else}
      <div class="bg-secondary/30 border-default rounded-lg border p-8">
        <div class="text-center">
          <div
            class="bg-secondary mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
          >
            <svg class="text-muted h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 15.5c-.77.833.192 2.5 1.732 2.5z"
              />
            </svg>
          </div>
          <h3 class="text-primary mb-2 text-lg font-medium">User Not Found</h3>
          <p class="text-muted">The requested user could not be found in the current date range.</p>
        </div>
      </div>
    {/if}
  </Page.Main>
</Page.Root>
