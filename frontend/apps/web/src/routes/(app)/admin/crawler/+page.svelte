<script lang="ts">
  import type { CrawlerProbe } from "@eneo/eneo-js";
  import { Activity, CheckCircle2, CircleGauge, Globe2, Loader2, ShieldCheck } from "lucide-svelte";
  import { enhance } from "$app/forms";
  import { Page, Settings } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { PageProps } from "./$types";

  const { data, form }: PageProps = $props();

  let selectedWebsiteId = $state("");
  let probing = $state(false);
  let probeResult = $state<CrawlerProbe | null>(null);
  let probeError = $state(false);

  const selectedWebsite = $derived(
    data.diagnostics.websites.find((website) => website.id === selectedWebsiteId)
  );

  $effect(() => {
    if (form?.websiteId) {
      selectedWebsiteId = form.websiteId;
    } else if (!selectedWebsiteId && data.diagnostics.websites[0]) {
      selectedWebsiteId = data.diagnostics.websites[0].id;
    }
    if (form) {
      probeResult = form.probeResult ?? null;
      probeError = Boolean(form.probeFailed);
    }
  });

  function bytes(value: number): string {
    return new Intl.NumberFormat("sv-SE", {
      style: "unit",
      unit: value >= 1024 * 1024 ? "megabyte" : "kilobyte",
      unitDisplay: "short",
      maximumFractionDigits: 1
    }).format(value / (value >= 1024 * 1024 ? 1024 * 1024 : 1024));
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.crawler_admin_nav()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.crawler_admin_nav()} />
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <div class="mx-auto flex w-full max-w-5xl flex-col gap-8 pb-12">
        <section aria-labelledby="crawler-overview" class="space-y-4">
          <div class="space-y-1">
            <h2 id="crawler-overview" class="text-primary text-lg font-semibold">
              {m.crawler_admin_engine_title()}
            </h2>
            <p class="text-secondary max-w-3xl text-sm leading-6">
              {m.crawler_admin_engine_description()}
            </p>
          </div>

          <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card.Root>
              <Card.Header class="space-y-3">
                <div
                  class="bg-positive-dimmer text-positive-stronger flex size-9 items-center justify-center rounded-lg"
                >
                  <CheckCircle2 class="size-5" aria-hidden="true" />
                </div>
                <div>
                  <Card.Title class="text-base">{m.crawler_admin_ready()}</Card.Title>
                  <Card.Description>{m.crawler_admin_ready_description()}</Card.Description>
                </div>
              </Card.Header>
            </Card.Root>
            <Card.Root>
              <Card.Header class="space-y-3">
                <div
                  class="bg-accent-dimmer text-accent-stronger flex size-9 items-center justify-center rounded-lg"
                >
                  <Activity class="size-5" aria-hidden="true" />
                </div>
                <div>
                  <Card.Title class="text-base">
                    {m.crawler_admin_crawl_capacity({
                      count: data.diagnostics.capacity.max_concurrent_crawl_jobs
                    })}
                  </Card.Title>
                  <Card.Description>
                    {#if data.diagnostics.capacity.reserved_worker_jobs !== null}
                      {m.crawler_admin_reserved_jobs({
                        reserved: data.diagnostics.capacity.reserved_worker_jobs,
                        total: data.diagnostics.capacity.worker_jobs_per_process
                      })}
                    {:else}
                      {m.crawler_admin_cluster_override()}
                    {/if}
                  </Card.Description>
                </div>
              </Card.Header>
            </Card.Root>
            <Card.Root>
              <Card.Header class="space-y-3">
                <div
                  class="bg-accent-dimmer text-accent-stronger flex size-9 items-center justify-center rounded-lg"
                >
                  <CircleGauge class="size-5" aria-hidden="true" />
                </div>
                <div>
                  <Card.Title class="text-base">
                    {m.crawler_admin_connections({
                      count: data.diagnostics.capacity.max_http_requests_per_process
                    })}
                  </Card.Title>
                  <Card.Description>
                    {m.crawler_admin_per_crawl({
                      count: data.diagnostics.capacity.requests_per_crawl
                    })}
                  </Card.Description>
                </div>
              </Card.Header>
            </Card.Root>
            <Card.Root>
              <Card.Header class="space-y-3">
                <div
                  class="bg-secondary text-primary flex size-9 items-center justify-center rounded-lg"
                >
                  <ShieldCheck class="size-5" aria-hidden="true" />
                </div>
                <div>
                  <Card.Title class="text-base">{m.crawler_admin_safe_fetch()}</Card.Title>
                  <Card.Description>{m.crawler_admin_safe_fetch_description()}</Card.Description>
                </div>
              </Card.Header>
            </Card.Root>
          </div>
        </section>

        <section aria-labelledby="crawler-limits" class="space-y-4">
          <h2 id="crawler-limits" class="text-primary text-lg font-semibold">
            {m.crawler_admin_limits()}
          </h2>
          <div
            class="border-default grid overflow-hidden rounded-xl border sm:grid-cols-2 lg:grid-cols-4"
          >
            <div class="border-default border-b p-4 sm:border-r lg:border-b-0">
              <p class="text-muted text-xs font-medium tracking-wide uppercase">
                {m.crawler_admin_pages()}
              </p>
              <p class="text-primary mt-1 text-xl font-semibold">
                {data.diagnostics.limits.max_pages.toLocaleString("sv-SE")}
              </p>
            </div>
            <div class="border-default border-b p-4 lg:border-r lg:border-b-0">
              <p class="text-muted text-xs font-medium tracking-wide uppercase">
                {m.crawler_admin_time_limit()}
              </p>
              <p class="text-primary mt-1 text-xl font-semibold">
                {m.crawler_admin_minutes({
                  count: Math.round(data.diagnostics.limits.max_crawl_seconds / 60)
                })}
              </p>
            </div>
            <div class="border-default border-b p-4 sm:border-r sm:border-b-0">
              <p class="text-muted text-xs font-medium tracking-wide uppercase">
                {m.crawler_admin_page_file()}
              </p>
              <p class="text-primary mt-1 text-xl font-semibold">
                {bytes(data.diagnostics.limits.max_page_bytes)} / {bytes(
                  data.diagnostics.limits.max_file_bytes
                )}
              </p>
            </div>
            <div class="p-4">
              <p class="text-muted text-xs font-medium tracking-wide uppercase">
                {m.crawler_admin_retries()}
              </p>
              <p class="text-primary mt-1 text-xl font-semibold">
                {data.diagnostics.limits.retries}
              </p>
            </div>
          </div>
        </section>

        <section aria-labelledby="crawler-probe" class="space-y-4">
          <div class="space-y-1">
            <h2 id="crawler-probe" class="text-primary text-lg font-semibold">
              {m.crawler_admin_probe_title()}
            </h2>
            <p class="text-secondary max-w-3xl text-sm leading-6">
              {m.crawler_admin_probe_description()}
            </p>
          </div>

          <Card.Root>
            <Card.Content class="space-y-5 pt-6">
              {#if data.diagnostics.websites.length === 0}
                <Alert.Root>
                  <Globe2 aria-hidden="true" />
                  <Alert.Title>{m.crawler_admin_no_websites()}</Alert.Title>
                  <Alert.Description>{m.crawler_admin_no_websites_description()}</Alert.Description>
                </Alert.Root>
              {:else}
                <form
                  method="POST"
                  action="?/probe"
                  class="flex flex-col gap-3 sm:flex-row sm:items-end"
                  use:enhance={() => {
                    probing = true;
                    probeError = false;
                    probeResult = null;
                    return async ({ result }) => {
                      probing = false;
                      if (result.type === "success" && result.data?.probeResult) {
                        probeResult = result.data.probeResult as CrawlerProbe;
                        return;
                      }
                      probeError = true;
                    };
                  }}
                >
                  <label
                    class="flex min-w-0 flex-1 flex-col gap-2 text-sm font-medium"
                    for="crawler-website"
                  >
                    {m.crawler_admin_website()}
                    <select
                      id="crawler-website"
                      name="website_id"
                      bind:value={selectedWebsiteId}
                      class="border-input bg-background ring-offset-background focus-visible:ring-ring h-10 w-full rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                      disabled={probing}
                    >
                      {#each data.diagnostics.websites as website (website.id)}
                        <option value={website.id}>{website.name} — {website.url}</option>
                      {/each}
                    </select>
                  </label>
                  <Button
                    type="submit"
                    disabled={!selectedWebsiteId || probing}
                    aria-busy={probing}
                  >
                    {#if probing}
                      <Loader2 class="animate-spin" aria-hidden="true" />
                      {m.crawler_admin_running_probe()}
                    {:else}
                      <Activity aria-hidden="true" />
                      {m.crawler_admin_run_probe()}
                    {/if}
                  </Button>
                </form>

                {#if selectedWebsite?.requires_http_auth}
                  <p class="text-muted text-xs">
                    {m.crawler_admin_auth_description()}
                  </p>
                {/if}

                {#if probeResult}
                  <div
                    aria-live="polite"
                    class="border-default bg-secondary/30 rounded-lg border p-4"
                  >
                    <div class="flex flex-wrap items-center gap-2">
                      <Badge
                        variant={probeResult.outcome === "reachable" ? "default" : "destructive"}
                      >
                        {probeResult.outcome === "reachable"
                          ? m.crawler_admin_outcome_reachable()
                          : probeResult.outcome === "unchanged"
                            ? m.crawler_admin_outcome_unchanged()
                            : probeResult.outcome === "partial"
                              ? m.crawler_admin_outcome_partial()
                              : m.crawler_admin_outcome_failed()}
                      </Badge>
                      <span class="text-muted text-sm">
                        {m.crawler_admin_duration_ms({ count: probeResult.duration_ms })}
                      </span>
                    </div>
                    <dl class="mt-4 grid gap-3 text-sm sm:grid-cols-3">
                      <div>
                        <dt class="text-muted">{m.crawler_admin_fetched_pages()}</dt>
                        <dd class="text-primary font-medium">{probeResult.pages_crawled}</dd>
                      </div>
                      <div>
                        <dt class="text-muted">{m.crawler_admin_failed_pages()}</dt>
                        <dd class="text-primary font-medium">{probeResult.pages_failed}</dd>
                      </div>
                      <div>
                        <dt class="text-muted">{m.crawler_admin_response()}</dt>
                        <dd class="text-primary truncate font-medium">
                          {probeResult.sample_title ?? probeResult.reason ?? "–"}
                        </dd>
                      </div>
                    </dl>
                  </div>
                {:else if probeError}
                  <Alert.Root variant="destructive" aria-live="assertive">
                    <Alert.Title>{m.crawler_admin_probe_error()}</Alert.Title>
                    <Alert.Description
                      >{m.crawler_admin_probe_error_description()}</Alert.Description
                    >
                  </Alert.Root>
                {/if}
              {/if}
            </Card.Content>
          </Card.Root>
        </section>
      </div>
    </Settings.Page>
  </Page.Main>
</Page.Root>
