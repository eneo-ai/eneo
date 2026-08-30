import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const updateMappedExecutionPolicy = vi.hoisted(() => vi.fn());
const getFlowRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceOrganizationFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceSpaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const getSpaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const getFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const listOrganizationFlowRunRetentionReviewQueue = vi.hoisted(() => vi.fn());
const listFlowRunRetentionSpaceTargets = vi.hoisted(() => vi.fn());
const listFlowRunRetentionFlowTargets = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    settings: {
      updateMappedExecutionPolicy,
      getFlowRetentionPolicy,
      replaceOrganizationFlowRunRetentionPolicy,
      replaceSpaceFlowRunRetentionPolicy,
      replaceFlowRunRetentionPolicy,
      getSpaceFlowRunRetentionPolicy,
      getFlowRunRetentionPolicy,
      listOrganizationFlowRunRetentionReviewQueue,
      listFlowRunRetentionSpaceTargets,
      listFlowRunRetentionFlowTargets
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

vi.mock("$app/state", () => ({
  page: {
    url: new URL("http://localhost/admin/flow-settings"),
    state: {}
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe: (run: (value: { url: URL; state: Record<string, unknown> }) => void) => {
      run({ url: new URL("http://localhost/admin/flow-settings"), state: {} });
      return () => undefined;
    }
  }
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
// eneo client, ...); the page itself only reads the settings payload below.
function pageProps(mappedOverrides: Record<string, unknown> = {}): PageProps {
  return { data: pageData(mappedOverrides) as never };
}

function pageData(mappedOverrides: Record<string, unknown> = {}) {
  return {
    flowRetentionPolicy: {
      run_debug_evidence_days: null,
      flow_runtime_upload_abandonment_days: null
    },
    flowRunRetentionPolicy: {
      scope: "organization",
      scope_id: "tenant-1",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    },
    flowRunRetentionReviewQueue: {
      items: [],
      count: 0,
      has_more: false,
      next_cursor: null
    },
    spaceTargets: {
      items: [
        { id: "space-1", name: "Inköp" },
        { id: "space-2", name: "Juridik" }
      ],
      count: 2,
      has_more: false
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

function reviewItem(runId: string, flowName: string) {
  return {
    run_id: runId,
    flow_id: `flow-${runId}`,
    flow_name: flowName,
    space_id: "space-1",
    space_name: "Inköp",
    status: "completed",
    retention_anchor: "2026-08-01T10:00:00Z",
    eligible_since: "2026-08-31T10:00:00Z",
    effective_policy: { mode: "review_required", days: 30 },
    policy_source: "organization"
  };
}

describe("flow settings page — mapped restore lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listOrganizationFlowRunRetentionReviewQueue.mockResolvedValue(
      pageData().flowRunRetentionReviewQueue
    );
    listFlowRunRetentionSpaceTargets.mockResolvedValue({
      items: [],
      count: 0,
      has_more: false
    });
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

  test("explains the safe retention default before editable controls", async () => {
    render(FlowSettingsPage, pageProps());

    const sectionHeadings = Array.from(document.querySelectorAll("h2"), (heading) =>
      heading.textContent?.trim()
    );

    expect(sectionHeadings[0]).toBe("Policy för körningshistorik");
    expect(sectionHeadings).toContain("Undantag för ytor och flöden");
    await expect
      .element(page.getByText("Att spara en policy raderar ingenting.", { exact: false }))
      .toBeVisible();
    await expect.element(page.getByText("Ingen tidsgräns", { exact: true })).toBeVisible();
    expect(page.getByText("Automatisk gallring", { exact: false }).query()).toBeNull();
  });

  test("saves mode and days together as one Organization policy", async () => {
    replaceOrganizationFlowRunRetentionPolicy.mockResolvedValue({
      scope: "organization",
      scope_id: "tenant-1",
      local_policy: { mode: "review_required", days: 30 },
      inherited_policy: null,
      effective: {
        state: "configured",
        mode: "review_required",
        effective_days: 30,
        source: "organization",
        contributors: {
          organization: { mode: "review_required", days: 30 },
          space: null,
          flow: null
        }
      }
    });
    render(FlowSettingsPage, pageProps());

    await page.getByLabelText("Gallringsbeteende för Organisation").click();
    await page.getByRole("option", { name: "Granska före gallring" }).click();
    await page.getByLabelText("Aktuell efter").fill("30");
    await page.getByRole("button", { name: "Spara policy för Organisation" }).click();

    expect(replaceOrganizationFlowRunRetentionPolicy).toHaveBeenCalledExactlyOnceWith({
      policy: { mode: "review_required", days: 30 }
    });
    await expect
      .element(page.getByText("30 dagar · Granska före gallring · från Organisation"))
      .toBeVisible();
  });

  test("does not discard an unsaved Space policy when scope switching is cancelled", async () => {
    getSpaceFlowRunRetentionPolicy.mockResolvedValue({
      scope: "space",
      scope_id: "space-1",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    });
    listFlowRunRetentionFlowTargets.mockResolvedValue({
      items: [],
      count: 0,
      has_more: false
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(FlowSettingsPage, pageProps());

    await page.getByRole("button", { name: "Yta", exact: true }).click();
    await page.getByRole("option", { name: "Inköp" }).click();
    await expect.element(page.getByText("Policy för ytan: Inköp")).toBeVisible();

    await page.getByLabelText("Gallringsbeteende för Yta").click();
    await page.getByRole("option", { name: "Granska före gallring" }).click();

    await page.getByRole("button", { name: "Yta", exact: true }).click();
    await page.getByRole("option", { name: "Juridik" }).click();

    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(getSpaceFlowRunRetentionPolicy).toHaveBeenCalledExactlyOnceWith({
      spaceId: "space-1"
    });
    await expect.element(page.getByText("Policy för ytan: Inköp")).toBeVisible();
    confirmSpy.mockRestore();
  });

  test("loads Space and Flow targets incrementally", async () => {
    const initial = pageData();
    listFlowRunRetentionSpaceTargets.mockResolvedValueOnce({
      items: [{ id: "space-3", name: "Ekonomi" }],
      count: 1,
      has_more: false
    });
    getSpaceFlowRunRetentionPolicy.mockResolvedValue({
      scope: "space",
      scope_id: "space-1",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    });
    listFlowRunRetentionFlowTargets
      .mockResolvedValueOnce({
        items: [{ id: "flow-1", space_id: "space-1", name: "Första flödet" }],
        count: 1,
        has_more: true
      })
      .mockResolvedValueOnce({
        items: [{ id: "flow-2", space_id: "space-1", name: "Andra flödet" }],
        count: 1,
        has_more: false
      });

    render(FlowSettingsPage, {
      data: {
        ...initial,
        spaceTargets: { ...initial.spaceTargets, has_more: true }
      } as never
    });

    await page.getByRole("button", { name: "Ladda fler ytor" }).click();
    expect(listFlowRunRetentionSpaceTargets).toHaveBeenCalledExactlyOnceWith({
      limit: 200,
      offset: 2
    });

    await page.getByRole("button", { name: "Yta", exact: true }).click();
    await expect.element(page.getByRole("option", { name: "Ekonomi" })).toBeVisible();
    await page.getByRole("option", { name: "Inköp" }).click();
    await expect.element(page.getByRole("button", { name: "Ladda fler flöden" })).toBeVisible();
    await page.getByRole("button", { name: "Ladda fler flöden" }).click();

    expect(listFlowRunRetentionFlowTargets).toHaveBeenNthCalledWith(1, {
      spaceId: "space-1",
      limit: 200,
      offset: 0
    });
    expect(listFlowRunRetentionFlowTargets).toHaveBeenNthCalledWith(2, {
      spaceId: "space-1",
      limit: 200,
      offset: 1
    });
  });

  test("moves forward and backward through review cursors", async () => {
    const initial = pageData();
    const firstQueue = {
      items: [reviewItem("run-1", "Första flödet")],
      count: 1,
      has_more: true,
      next_cursor: "cursor-2"
    };
    const secondQueue = {
      items: [reviewItem("run-2", "Andra flödet")],
      count: 1,
      has_more: false,
      next_cursor: null
    };
    listOrganizationFlowRunRetentionReviewQueue
      .mockResolvedValueOnce(secondQueue)
      .mockResolvedValueOnce(firstQueue);
    render(FlowSettingsPage, {
      data: { ...initial, flowRunRetentionReviewQueue: firstQueue } as never
    });

    await page.getByRole("button", { name: "Nästa" }).click();
    await expect.element(page.getByText("Andra flödet")).toBeVisible();
    await page.getByRole("button", { name: "Föregående" }).click();
    await expect.element(page.getByText("Första flödet")).toBeVisible();

    expect(listOrganizationFlowRunRetentionReviewQueue).toHaveBeenNthCalledWith(1, {
      limit: 50,
      cursor: "cursor-2"
    });
    expect(listOrganizationFlowRunRetentionReviewQueue).toHaveBeenNthCalledWith(2, {
      limit: 50,
      cursor: undefined
    });
  });

  test("retries the review page that failed", async () => {
    const initial = pageData();
    const firstQueue = {
      items: [reviewItem("run-1", "Första flödet")],
      count: 1,
      has_more: true,
      next_cursor: "cursor-2"
    };
    const secondQueue = {
      items: [reviewItem("run-2", "Andra flödet")],
      count: 1,
      has_more: false,
      next_cursor: null
    };
    listOrganizationFlowRunRetentionReviewQueue
      .mockRejectedValueOnce(new Error("temporary queue failure"))
      .mockResolvedValueOnce(secondQueue);
    render(FlowSettingsPage, {
      data: { ...initial, flowRunRetentionReviewQueue: firstQueue } as never
    });

    await page.getByRole("button", { name: "Nästa" }).click();
    await expect.element(page.getByText("Granskningslistan kunde inte hämtas")).toBeVisible();
    await page.getByRole("button", { name: "Uppdatera listan" }).click();
    await expect.element(page.getByText("Andra flödet")).toBeVisible();

    expect(listOrganizationFlowRunRetentionReviewQueue).toHaveBeenNthCalledWith(1, {
      limit: 50,
      cursor: "cursor-2"
    });
    expect(listOrganizationFlowRunRetentionReviewQueue).toHaveBeenNthCalledWith(2, {
      limit: 50,
      cursor: "cursor-2"
    });
  });

  test("keeps policy controls available when the review queue is unavailable", async () => {
    render(FlowSettingsPage, {
      data: { ...pageData(), flowRunRetentionReviewQueue: null } as never
    });

    await expect.element(page.getByText("Granskningslistan kunde inte hämtas")).toBeVisible();
    await expect
      .element(page.getByText("Policy för körningshistorik", { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "Spara policy för Organisation" }))
      .toBeVisible();
  });

  test("uses task-oriented names for every settings tab", async () => {
    render(FlowSettingsPage, pageProps());

    await expect.element(page.getByRole("tab", { name: "Gallring och bevarande" })).toBeVisible();
    await expect
      .element(page.getByRole("tab", { name: "Uppladdningar och körtider" }))
      .toBeVisible();
    await expect.element(page.getByRole("tab", { name: "AI-byggaren" })).toBeVisible();
    await expect.element(page.getByRole("tab", { name: "Sparat källunderlag" })).toBeVisible();
  });

  test("upload ceilings say what they are and where they are raised", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    // Without the provenance an admin sees a limit they cannot explain or
    // raise, because it is owned by the deployment-wide storage policy.
    await expect
      .element(
        page.getByText(
          "Räcker till ungefär 3 h 38 min tal som MP3 i 128 kbit/s. Verklig speltid varierar med format och inspelningskvalitet. Högsta tillåtna värde: 200 MiB. Taket gäller hela driftmiljön och ändras av en lagringsadministratör under Admin > Fillagring."
        )
      )
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          "Högsta tillåtna värde: 10 MiB. Taket gäller hela driftmiljön och ändras av en lagringsadministratör under Admin > Fillagring."
        )
      )
      .toBeVisible();
  });

  test("states the recording time an audio limit buys, and follows the value", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    // 200 MiB of 128 kbit/s MP3 is roughly 3 h 38 min of speech.
    await expect
      .element(
        page.getByText("Räcker till ungefär 3 h 38 min tal som MP3 i 128 kbit/s.", { exact: false })
      )
      .toBeVisible();

    await page.getByRole("textbox", { name: "Största ljudfil" }).fill("60");

    await expect
      .element(
        page.getByText("Räcker till ungefär 1 h 6 min tal som MP3 i 128 kbit/s.", { exact: false })
      )
      .toBeVisible();
  });

  test("hides the running time while the audio size is invalid", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    // Above the ceiling: an estimate here would read as the entered value's.
    await page.getByRole("textbox", { name: "Största ljudfil" }).fill("300");

    expect(page.getByText("Räcker till ungefär", { exact: false }).query()).toBeNull();
    await expect
      .element(page.getByText("Högsta tillåtna värde: 200 MiB.", { exact: false }))
      .toBeVisible();
  });

  test("dirty upload rows expose row-specific undo actions without repeated default links", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    expect(page.getByRole("button", { name: /Återställ till standard:/ }).query()).toBeNull();

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

  test("reveals low-frequency runtime limits and keeps invalid edits visible", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const trigger = page.getByRole("button", { name: /Avancerad driftstyrning/ });
    expect(page.getByRole("textbox", { name: "Normal tidsgräns per steg" }).query()).toBeNull();
    await trigger.click();
    const normalLimit = page.getByRole("textbox", { name: "Normal tidsgräns per steg" });
    await normalLimit.fill("4000");
    await trigger.click();

    await expect.element(normalLimit).toBeVisible();
    await expect.element(page.getByText(/Ange ett värde mellan/)).toBeVisible();
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

  test("summarizes the effective source-text budget in human units", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Sparat källunderlag" }).click();

    await expect.element(page.getByText("Med de här värdena")).toBeVisible();
    await expect
      .element(
        page.getByText(
          "Högst 25 källor och 5 textavsnitt per källa sparas, sammanlagt högst 128 KB per steg."
        )
      )
      .toBeVisible();
  });
});
