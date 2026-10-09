import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const updateMappedExecutionPolicy = vi.hoisted(() => vi.fn());
const updateAIBuilderBudgetSettings = vi.hoisted(() => vi.fn());
const getFlowRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceOrganizationFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceSpaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const replaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const getSpaceFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const getFlowRunRetentionPolicy = vi.hoisted(() => vi.fn());
const listOrganizationFlowRunRetentionReviewQueue = vi.hoisted(() => vi.fn());
const listFlowRunRetentionSpaceTargets = vi.hoisted(() => vi.fn());
const listFlowRunRetentionFlowTargets = vi.hoisted(() => vi.fn());
const listFlowRetentionHolds = vi.hoisted(() => vi.fn());
const placeFlowRetentionHold = vi.hoisted(() => vi.fn());
const releaseFlowRetentionHold = vi.hoisted(() => vi.fn());
const updateFlowInputLimits = vi.hoisted(() => vi.fn());
const updateFlowRuntimePolicy = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastErrorFn = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    settings: {
      updateFlowInputLimits,
      updateFlowRuntimePolicy,
      updateMappedExecutionPolicy,
      updateAIBuilderBudgetSettings,
      getFlowRetentionPolicy,
      replaceOrganizationFlowRunRetentionPolicy,
      replaceSpaceFlowRunRetentionPolicy,
      replaceFlowRunRetentionPolicy,
      getSpaceFlowRunRetentionPolicy,
      getFlowRunRetentionPolicy,
      listOrganizationFlowRunRetentionReviewQueue,
      listFlowRunRetentionSpaceTargets,
      listFlowRunRetentionFlowTargets,
      listFlowRetentionHolds,
      placeFlowRetentionHold,
      releaseFlowRetentionHold
    }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { success: toastSuccess, error: toastErrorFn }
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
import { BUILDER_BUDGET, pageData } from "./flow-settings-test-data";
import { addLocalDays, endOfLocalDay, localDate } from "./flowRetentionHold";

type PageProps = { data: never };

// The page's data prop type includes the whole layout payload (user, tenant,
// eneo client, ...); the page itself only reads the settings payload below.
function pageProps(
  mappedOverrides: Record<string, unknown> = {},
  builderOverrides: Record<string, unknown> = {}
): PageProps {
  return { data: pageData(mappedOverrides, builderOverrides) as never };
}

function pagePropsWithRunPolicy(overrides: Record<string, unknown>): PageProps {
  const data = pageData();
  return {
    data: { ...data, flowRuntimePolicy: { ...data.flowRuntimePolicy, ...overrides } } as never
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
      .element(page.getByRole("textbox", { name: "Nya steg som körs per fil: Högst" }))
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
    await page.getByLabelText("Kan gallras efter").fill("30");
    await page.getByRole("button", { name: "Spara policy för organisationen" }).click();

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

    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Inköp" }).click();
    await expect.element(page.getByText("Policy för ytan: Inköp")).toBeVisible();

    await page.getByLabelText("Gallringsbeteende för ytan").click();
    await page.getByRole("option", { name: "Granska före gallring" }).click();

    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Juridik" }).click();

    expect(confirmSpy).toHaveBeenCalledOnce();
    expect(getSpaceFlowRunRetentionPolicy).toHaveBeenCalledExactlyOnceWith({
      spaceId: "space-1"
    });
    await expect.element(page.getByText("Policy för ytan: Inköp")).toBeVisible();
    confirmSpy.mockRestore();
  });

  test("marks a deleted Flow and says what choosing it means", async () => {
    const offPolicy = (scope: "space" | "flow", scopeId: string) => ({
      scope,
      scope_id: scopeId,
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
    getSpaceFlowRunRetentionPolicy.mockResolvedValue(offPolicy("space", "space-1"));
    getFlowRunRetentionPolicy.mockResolvedValue(offPolicy("flow", "flow-old"));
    listFlowRunRetentionFlowTargets.mockResolvedValue({
      items: [
        { id: "flow-live", space_id: "space-1", name: "Aktivt flöde", retired: false },
        { id: "flow-old", space_id: "space-1", name: "Gammalt flöde", retired: true }
      ],
      count: 2,
      has_more: false
    });
    render(FlowSettingsPage, pageProps());

    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Inköp" }).click();
    await page.getByRole("combobox", { name: "Flöde" }).click();

    await expect.element(page.getByRole("option", { name: "Gammalt flöde Raderat" })).toBeVisible();
    await expect.element(page.getByRole("option", { name: "Aktivt flöde" })).toBeVisible();
    await expect
      .element(page.getByRole("option", { name: "Aktivt flöde" }).getByText("Raderat"))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("Flödet är raderat och kan inte längre köras."))
      .not.toBeInTheDocument();

    await page.getByRole("option", { name: "Gammalt flöde Raderat" }).click();

    await expect
      .element(
        page.getByText(
          "Flödet är raderat och kan inte längre köras. Historiken går att läsa och följer flödets gallringsregel."
        )
      )
      .toBeVisible();
    expect(getFlowRunRetentionPolicy).toHaveBeenCalledExactlyOnceWith({ flowId: "flow-old" });
  });

  test("marks a held Flow, explains it, and places a hold on the chosen Flow", async () => {
    const offPolicy = {
      scope: "flow",
      scope_id: "flow-held",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    };
    getSpaceFlowRunRetentionPolicy.mockResolvedValue({ ...offPolicy, scope: "space" });
    getFlowRunRetentionPolicy.mockResolvedValue(offPolicy);
    const targets = (held: boolean) => ({
      items: [
        { id: "flow-free", space_id: "space-1", name: "Fritt flöde", retired: false, held: false },
        { id: "flow-held", space_id: "space-1", name: "Spärrat flöde", retired: false, held }
      ],
      count: 2,
      has_more: false
    });
    listFlowRunRetentionFlowTargets.mockResolvedValueOnce(targets(false));
    listFlowRunRetentionFlowTargets.mockResolvedValue(targets(true));
    placeFlowRetentionHold.mockResolvedValue({ holds: [] });
    listFlowRetentionHolds.mockResolvedValue({
      items: [],
      has_more: false,
      review_limit_days: 365
    });
    render(FlowSettingsPage, pageProps());

    await expect.element(page.getByRole("button", { name: "Lägg spärr" })).toBeDisabled();
    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Inköp" }).click();
    await page.getByRole("combobox", { name: "Flöde" }).click();
    await expect.element(page.getByRole("option", { name: "Spärrat flöde" })).toBeVisible();
    await expect
      .element(page.getByRole("option", { name: "Spärrat flöde" }).getByText("Spärrad"))
      .not.toBeInTheDocument();
    await page.getByRole("option", { name: "Spärrat flöde" }).click();

    await page.getByRole("button", { name: "Lägg spärr på Spärrat flöde" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Skäl" }).fill("Begäran om utlämnande");
    const review = addLocalDays(localDate(new Date()), 30);
    await dialog.getByLabelText("Omprövas senast").fill(review);
    await dialog.getByRole("button", { name: "Lägg spärr" }).click();

    await vi.waitFor(() =>
      expect(placeFlowRetentionHold).toHaveBeenCalledExactlyOnceWith({
        flowId: "flow-held",
        runIds: null,
        reason: "Begäran om utlämnande",
        reviewBy: endOfLocalDay(review),
        endsAt: null
      })
    );
    await expect
      .element(
        page.getByText(
          "Flödet har en rättslig spärr. Spärrad historik gallras inte, oavsett policy."
        )
      )
      .toBeVisible();
    await page.getByRole("combobox", { name: "Flöde" }).click();
    await expect.element(page.getByRole("option", { name: "Spärrat flöde Spärrad" })).toBeVisible();
    await expect
      .element(page.getByRole("option", { name: "Fritt flöde" }).getByText("Spärrad"))
      .not.toBeInTheDocument();
  });

  test("a placed hold refreshes the hold marks on every loaded page of Flows", async () => {
    const offPolicy = {
      scope: "flow",
      scope_id: "flow-200",
      local_policy: null,
      inherited_policy: null,
      effective: {
        state: "off",
        mode: null,
        effective_days: null,
        source: "none",
        contributors: { organization: null, space: null, flow: null }
      }
    };
    getSpaceFlowRunRetentionPolicy.mockResolvedValue({ ...offPolicy, scope: "space" });
    getFlowRunRetentionPolicy.mockResolvedValue(offPolicy);
    const flowsPage = (start: number, count: number, held: boolean, hasMore: boolean) => ({
      items: Array.from({ length: count }, (_, index) => ({
        id: `flow-${start + index}`,
        space_id: "space-1",
        name: `Flöde ${String(start + index).padStart(3, "0")}`,
        retired: false,
        held: held && start + index === 200
      })),
      count,
      has_more: hasMore
    });
    listFlowRunRetentionFlowTargets.mockImplementation(async ({ offset }: { offset: number }) =>
      offset === 0
        ? flowsPage(0, 200, false, true)
        : flowsPage(200, 1, placeFlowRetentionHold.mock.calls.length > 0, false)
    );
    placeFlowRetentionHold.mockResolvedValue({ holds: [] });
    listFlowRetentionHolds.mockResolvedValue({
      items: [],
      has_more: false,
      review_limit_days: 365
    });
    render(FlowSettingsPage, pageProps());

    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Inköp" }).click();
    await page.getByRole("combobox", { name: "Flöde" }).click();
    await page.getByRole("option", { name: "Ladda fler flöden" }).click();
    await page.getByRole("option", { name: "Flöde 200" }).click();

    await page.getByRole("button", { name: "Lägg spärr på Flöde 200" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Skäl" }).fill("Begäran om utlämnande");
    await dialog.getByLabelText("Omprövas senast").fill(addLocalDays(localDate(new Date()), 30));
    await dialog.getByRole("button", { name: "Lägg spärr" }).click();

    await vi.waitFor(() =>
      expect(listFlowRunRetentionFlowTargets).toHaveBeenCalledWith({
        spaceId: "space-1",
        limit: 200,
        offset: 200
      })
    );
    await expect
      .element(
        page.getByText(
          "Flödet har en rättslig spärr. Spärrad historik gallras inte, oavsett policy."
        )
      )
      .toBeVisible();
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

    // Loading the next page happens inside the open list, so the admin never
    // loses their place to fetch more.
    await page.getByRole("combobox", { name: "Yta" }).click();
    await page.getByRole("option", { name: "Ladda fler ytor" }).click();
    expect(listFlowRunRetentionSpaceTargets).toHaveBeenCalledExactlyOnceWith({
      limit: 200,
      offset: 2
    });

    await expect.element(page.getByRole("option", { name: "Ekonomi" })).toBeVisible();
    await page.getByRole("option", { name: "Inköp" }).click();

    await page.getByRole("combobox", { name: "Flöde" }).click();
    await page.getByRole("option", { name: "Ladda fler flöden" }).click();

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
      .element(page.getByRole("button", { name: "Spara policy för organisationen" }))
      .toBeVisible();
  });

  test("uses task-oriented names for every settings tab", async () => {
    render(FlowSettingsPage, pageProps());

    await expect.element(page.getByRole("tab", { name: "Gallring och bevarande" })).toBeVisible();
    await expect
      .element(page.getByRole("tab", { name: "Uppladdningar och körtider" }))
      .toBeVisible();
    await expect.element(page.getByRole("tab", { name: "AI-byggaren" })).toBeVisible();
    await expect.element(page.getByRole("tab", { name: "Sparad källtext" })).toBeVisible();
  });

  test("shows shared upload sizes with a link to their only editor", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();
    await expect.element(page.getByText("10 MiB", { exact: true })).toBeVisible();
    await expect.element(page.getByText("200 MiB", { exact: true })).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "Hantera i Fillagring" }).first())
      .toHaveAttribute("href", "/admin/storage");
    for (const name of ["Största filstorlek", "Största ljudfil"]) {
      expect(page.getByRole("textbox", { name }).query()).toBeNull();
    }
    await expect
      .element(page.getByText("Räcker till ungefär 3 h 38 min tal i MP3.", { exact: false }))
      .toBeVisible();
  });

  test("the longest recording is set in minutes, up to the deployment's ceiling", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const field = page.getByRole("textbox", { name: "Längsta inspelning" });
    await expect.element(field).toHaveValue("300");
    // The minutes read as hours, then the deployment's ceiling: one line each.
    await expect.element(page.getByText("Motsvarar 5 h.", { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("Högsta tillåtna värde: 480 min (8 h).", { exact: true }))
      .toBeVisible();
    await field.fill("90");
    await expect.element(page.getByText("Motsvarar 1 h 30 min.", { exact: false })).toBeVisible();

    await field.fill("481");
    // An invalid entry has no hours to state: only the ceiling and the error describe it.
    await expect.element(field).not.toHaveAccessibleDescription(/Motsvarar/);
    await expect
      .element(field)
      .toHaveAccessibleDescription(/Högsta tillåtna värde: 480 min \(8 h\)/);
    await expect.element(field).toHaveAttribute("aria-invalid", "true");
  });

  test("the longest recording saves in seconds, and an empty field returns to the deployment default", async () => {
    const limits = pageData().flowInputLimits;
    updateFlowInputLimits.mockResolvedValueOnce({
      ...limits,
      audio_max_duration_seconds: 6 * 60 * 60
    });
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const field = page.getByRole("textbox", { name: "Längsta inspelning" });
    await field.fill("360");
    await page.getByRole("button", { name: "Spara ändringar" }).click();
    expect(updateFlowInputLimits).toHaveBeenLastCalledWith({ audio_max_duration_seconds: 21_600 });
    await expect.element(field).toHaveValue("360");

    updateFlowInputLimits.mockResolvedValueOnce(limits);
    await field.fill("");
    await page.getByRole("button", { name: "Spara ändringar" }).click();
    expect(updateFlowInputLimits).toHaveBeenLastCalledWith({ audio_max_duration_seconds: null });
  });

  test("max concurrent flow runs states the server capacity and refuses more", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const field = page.getByRole("textbox", { name: "Högsta antal samtidiga flödeskörningar" });
    await expect.element(field).toHaveValue("4");
    await expect.element(page.getByText(/Upp till 8, vilket är vad servern klarar/)).toBeVisible();

    await field.fill("9");
    await expect.element(field).toHaveAttribute("aria-invalid", "true");
    await expect.element(page.getByText(/Ange ett värde mellan 1 och 8/)).toBeVisible();
    await field.fill("0");
    await expect.element(field).toHaveAttribute("aria-invalid", "true");
    await field.fill("");
    await expect.element(field).toHaveAttribute("aria-invalid", "true");
    await field.fill("2");
    expect(field.query()?.getAttribute("aria-invalid")).toBeNull();
  });

  test("max concurrent flow runs saves, and the server capacity restores the default", async () => {
    const policy = pageData().flowRuntimePolicy;
    updateFlowRuntimePolicy.mockResolvedValueOnce({ ...policy, max_concurrent_runs: 2 });
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const field = page.getByRole("textbox", { name: "Högsta antal samtidiga flödeskörningar" });
    await field.fill("2");
    await page.getByRole("button", { name: "Spara ändringar" }).click();
    expect(updateFlowRuntimePolicy).toHaveBeenLastCalledWith({ max_concurrent_runs: 2 });
    await expect.element(field).toHaveValue("2");

    // The server stores the capacity as no override and returns it as the effective value.
    updateFlowRuntimePolicy.mockResolvedValueOnce({ ...policy, max_concurrent_runs: 8 });
    await field.fill("8");
    await page.getByRole("button", { name: "Spara ändringar" }).click();
    expect(updateFlowRuntimePolicy).toHaveBeenLastCalledWith({ max_concurrent_runs: 8 });
    await expect.element(field).toHaveValue("8");
    expect(page.getByText("1 osparad ändring").query()).toBeNull();
  });

  test("a saved value the capacity clamps is shown, and one click returns to the capacity", async () => {
    const policy = pageData().flowRuntimePolicy;
    updateFlowRuntimePolicy.mockResolvedValueOnce({
      ...policy,
      max_concurrent_runs: 3,
      max_concurrent_runs_capacity: 3,
      max_concurrent_runs_override: null
    });
    render(
      FlowSettingsPage,
      pagePropsWithRunPolicy({
        max_concurrent_runs: 3,
        max_concurrent_runs_capacity: 3,
        max_concurrent_runs_override: 6
      })
    );
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    const field = page.getByRole("textbox", { name: "Högsta antal samtidiga flödeskörningar" });
    await expect.element(field).toHaveValue("3");
    await expect
      .element(
        page.getByText(
          "Begränsas till 3 eftersom servern inte klarar fler. Det sparade värdet är 6."
        )
      )
      .toBeVisible();

    // Entering the shown number is not a change, so the explicit action is what resets it.
    await page.getByRole("button", { name: "Använd serverns kapacitet" }).click();

    expect(updateFlowRuntimePolicy).toHaveBeenLastCalledWith({ max_concurrent_runs: null });
    await expect.element(page.getByText(/sparat värde 6/)).not.toBeInTheDocument();
    expect(page.getByRole("button", { name: "Använd serverns kapacitet" }).query()).toBeNull();
  });

  test("the reset action is absent while the setting follows the capacity", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    expect(page.getByRole("button", { name: "Använd serverns kapacitet" }).query()).toBeNull();
  });

  test("a server capacity of 0 says no run can start instead of a 0-to-0 range", async () => {
    render(
      FlowSettingsPage,
      pagePropsWithRunPolicy({ max_concurrent_runs: 0, max_concurrent_runs_capacity: 0 })
    );
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    await expect
      .element(page.getByText("Inga nya flödeskörningar kan starta: serverns kapacitet är 0."))
      .toBeVisible();
    await page.getByRole("textbox", { name: "Högsta antal samtidiga flödeskörningar" }).fill("3");
    expect(page.getByText(/Ange ett värde mellan 0 och 0/).query()).toBeNull();
    await expect.element(page.getByRole("button", { name: "Spara ändringar" })).toBeDisabled();
  });

  test("a refusal for exceeding the server capacity is shown in the page language", async () => {
    const { EneoError } = await import("@eneo/eneo-js");
    updateFlowRuntimePolicy.mockRejectedValueOnce(
      new EneoError("exceeds", "SERVER", 400, 9007, {
        code: "max_concurrent_runs_exceeds_server_capacity"
      })
    );
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Uppladdningar och körtider" }).click();

    await page.getByRole("textbox", { name: "Högsta antal samtidiga flödeskörningar" }).fill("2");
    await page.getByRole("button", { name: "Spara ändringar" }).click();

    expect(toastErrorFn).toHaveBeenCalledExactlyOnceWith(
      "Högsta antal samtidiga flödeskörningar får inte överstiga serverns kapacitet. Ladda om sidan för att se aktuell kapacitet."
    );
    expect(toastErrorMock).not.toHaveBeenCalled();
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

  test("the investigation evidence row is bounded by the ceiling the server reports", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "AI-byggaren" }).click();

    const row = page.getByRole("textbox", { name: "Underlag när ett förslag undersöks" });
    await expect.element(row).toHaveValue("16000");
    await expect.element(page.getByText("Systemets högsta tillåtna värde: 16000")).toBeVisible();

    // Above the ceiling stays visible as an error; the server would refuse it.
    await row.fill("16001");
    await expect.element(row).toHaveAttribute("aria-invalid", "true");
    await expect.element(page.getByText(/Ange ett värde mellan/)).toBeVisible();

    await row.fill("12000");
    expect(row.query()?.getAttribute("aria-invalid")).toBeNull();
  });

  test("entering the system bound saves it and the row re-baselines to the bound", async () => {
    // The server stores the bound as no override; the page only has to send
    // the bound and adopt the response.
    updateAIBuilderBudgetSettings.mockResolvedValue({ ...BUILDER_BUDGET });
    render(FlowSettingsPage, pageProps({}, { review_investigation_evidence_max_tokens: 12_000 }));
    await page.getByRole("tab", { name: "AI-byggaren" }).click();

    const row = page.getByRole("textbox", { name: "Underlag när ett förslag undersöks" });
    await expect.element(row).toHaveValue("12000");
    await row.fill("16000");
    await expect.element(page.getByText("1 osparad ändring")).toBeVisible();
    await page.getByRole("button", { name: "Spara ändringar" }).click();

    expect(updateAIBuilderBudgetSettings).toHaveBeenCalledExactlyOnceWith({
      review_investigation_evidence_max_tokens: 16_000
    });
    await expect.element(row).toHaveValue("16000");
    expect(page.getByText("1 osparad ändring").query()).toBeNull();
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
        page.getByText(
          "Den sparade inställningen är ogiltig, och nya steg som körs per fil är blockerade.",
          {
            exact: false
          }
        )
      )
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: /Återställ till driftmiljöns standard/ }))
      .toBeVisible();
  });

  test("summarizes the effective source-text budget in human units", async () => {
    render(FlowSettingsPage, pageProps());
    await page.getByRole("tab", { name: "Sparad källtext" }).click();

    await expect.element(page.getByText("Med de här värdena")).toBeVisible();
    await expect
      .element(
        page.getByText(
          "Högst 25 källor och 5 textavsnitt per källa sparas, sammanlagt högst 128 KiB per steg."
        )
      )
      .toBeVisible();
  });
});
