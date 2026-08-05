import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const updateMappedExecutionPolicy = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    settings: {
      updateMappedExecutionPolicy
    }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { success: toastSuccess, error: vi.fn() }
}));

vi.mock("$lib/core/errors", () => ({
  toastError: toastErrorMock
}));

// Self-contained mocks: importing SvelteKit's real client runtime outside a
// router hangs the browser-mode run.
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate: vi.fn(),
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  replaceState: vi.fn()
}));

vi.mock("$app/paths", () => ({
  assets: "",
  base: "",
  asset: (path: string) => path,
  resolve: (path: string) => path,
  resolveRoute: (path: string) => path
}));

vi.mock("$lib/paraglide/messages", async () => {
  const { default: swedishMessages } = await import("../../../../../messages/sv.json");

  return {
    m: new Proxy<Record<string, unknown>>(
      {},
      {
        get: (_target, key) => {
          const label = String(key);
          return (params?: Record<string, unknown>) => {
            const template = (swedishMessages as Record<string, string>)[label];
            if (typeof template !== "string") {
              return params ? `${label} ${JSON.stringify(params)}` : label;
            }
            return template.replace(/\{(\w+)\}/g, (_match, name: string) =>
              String(params?.[name] ?? `{${name}}`)
            );
          };
        }
      }
    )
  };
});

vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv"
}));

import FlowSettingsPage from "./+page.svelte";

type PageProps = { data: never };

// The page's data prop type includes the whole layout payload (user, tenant,
// eneo client, ...); the page itself only reads the six policy objects below.
function pageProps(mappedOverrides: Record<string, unknown> = {}): PageProps {
  return { data: pageData(mappedOverrides) as never };
}

function pageData(mappedOverrides: Record<string, unknown> = {}) {
  return {
    flowRetentionPolicy: {
      flow_run_history_retention_days: null,
      flow_run_history_minimum_retention_days: null,
      flow_run_history_no_purge: false,
      flow_runtime_upload_abandonment_days: null,
      effective_state: {
        run_history_deletion_active: false,
        runtime_upload_abandonment_active: false,
        classification_policy_count: 0,
        activation_sources: [],
        barrier_sources: []
      }
    },
    flowInputLimits: {
      file_max_size_bytes: 10 * 1024 * 1024,
      audio_max_size_bytes: 200 * 1024 * 1024,
      max_files_per_run: null,
      audio_max_files_per_run: 10,
      file_max_size_ceiling_bytes: 10 * 1024 * 1024,
      audio_max_size_ceiling_bytes: 200 * 1024 * 1024
    },
    flowRuntimePolicy: {
      default_step_timeout_seconds: 600,
      max_step_timeout_seconds: 3540,
      hard_ceiling_seconds: 3540
    },
    mappedExecutionPolicy: {
      version: 1,
      max_provider_calls_per_mapped_step: 40,
      max_estimated_input_tokens_per_mapped_step: null,
      max_provider_calls_source: "organization",
      deployment_default_max_provider_calls: 100,
      ...mappedOverrides
    },
    aiBuilderBudgetSettings: {
      max_attachments: 100,
      max_message_chars: 50_000,
      max_attachments_hard_limit: 100,
      max_message_chars_hard_limit: 50_000
    },
    ragEvidencePolicy: {
      max_sources_with_recorded_passages: 25,
      max_recorded_passages_per_source: 5,
      max_recorded_passage_bytes: 4096,
      max_recorded_passage_bytes_per_step: 131_072
    }
  };
}

describe("flow settings page — mapped restore lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("restores the deployment default and re-baselines without touching other edits", async () => {
    updateMappedExecutionPolicy.mockResolvedValue({
      version: 1,
      max_provider_calls_per_mapped_step: 100,
      max_estimated_input_tokens_per_mapped_step: null,
      max_provider_calls_source: "deployment_default",
      deployment_default_max_provider_calls: 100
    });
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "AI-byggaren" }).click();

    // make an unrelated field dirty first
    const attachments = page.getByRole("textbox", { name: "Bilagor per session" });
    await attachments.fill("50");
    await expect.element(page.getByText("1 osparad ändring")).toBeVisible();

    const restore = page.getByRole("button", {
      name: "Återställ till driftmiljöns standard (100 anrop)"
    });
    await expect.element(restore).toBeVisible();
    await restore.click();

    expect(updateMappedExecutionPolicy).toHaveBeenCalledExactlyOnceWith({
      restore_max_provider_calls_default: true
    });
    // re-baselined to the returned resolved state: inherited hint appears…
    await expect.element(page.getByText("Följer driftmiljöns standard.")).toBeVisible();
    // …the mapped field adopts the returned inherited value as a clean baseline…
    await expect
      .element(page.getByRole("textbox", { name: "Nya mappade steg: Högst" }))
      .toHaveValue("100");
    // …while the unrelated attachment edit stays the only dirty field.
    await expect.element(page.getByText("1 osparad ändring")).toBeVisible();
    expect(toastSuccess).toHaveBeenCalled();
  });

  test("repeated undo and restore controls carry row-specific accessible names", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Körningar" }).click();

    // uploads tab renders two populated size fields with restore links
    const fileRestore = page.getByRole("button", {
      name: "Återställ till standard: Största filstorlek"
    });
    const audioRestore = page.getByRole("button", {
      name: "Återställ till standard: Största ljudfil"
    });
    await expect.element(fileRestore).toBeVisible();
    await expect.element(audioRestore).toBeVisible();

    // dirty two rows and expect two distinct undo names
    await page.getByRole("textbox", { name: "Största filstorlek" }).fill("5");
    await page.getByRole("textbox", { name: "Största ljudfil" }).fill("50");
    await expect
      .element(page.getByRole("button", { name: "Ignorera ändringar: Största filstorlek" }))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "Ignorera ändringar: Största ljudfil" }))
      .toBeVisible();
  });

  test("inherited state shows the hint and offers no restore action", async () => {
    render(FlowSettingsPage, pageProps({ max_provider_calls_source: "deployment_default" }));
    await page.getByRole("tab", { name: "AI-byggaren" }).click();

    await expect.element(page.getByText("Följer driftmiljöns standard.")).toBeVisible();
    expect(
      page.getByRole("button", { name: /Återställ till driftmiljöns standard/ }).query()
    ).toBeNull();
  });

  test("corrupt stored state surfaces the invalid alert with a repair path", async () => {
    render(
      FlowSettingsPage,
      pageProps({
        max_provider_calls_per_mapped_step: null,
        max_provider_calls_source: "invalid"
      })
    );
    await page.getByRole("tab", { name: "AI-byggaren" }).click();

    await expect
      .element(
        page.getByText("Den sparade inställningen är ogiltig och nya mappade steg är blockerade.", {
          exact: false
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: /Återställ till driftmiljöns standard/ }))
      .toBeVisible();
  });
});
