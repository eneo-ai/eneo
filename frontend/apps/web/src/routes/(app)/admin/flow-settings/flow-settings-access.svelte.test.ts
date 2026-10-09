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
const replaceFlowRetentionHoldReviewLimit = vi.hoisted(() => vi.fn());
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
      releaseFlowRetentionHold,
      replaceFlowRetentionHoldReviewLimit
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
import { pageData } from "./flow-settings-test-data";

type Access = { admin: boolean; retentionManage: boolean; retentionHolds: boolean };

// What the loader returns for each permission set (see +page.ts): admin-only
// settings for admins, retention data for retention permissions.
function dataFor(access: Access) {
  const full = pageData();
  const retention = access.retentionManage || access.retentionHolds;
  return {
    ...full,
    access,
    flowRetentionPolicy: access.admin ? full.flowRetentionPolicy : null,
    flowInputLimits: access.admin ? full.flowInputLimits : null,
    flowRuntimePolicy: access.admin ? full.flowRuntimePolicy : null,
    mappedExecutionPolicy: access.admin ? full.mappedExecutionPolicy : null,
    aiBuilderBudgetSettings: access.admin ? full.aiBuilderBudgetSettings : null,
    ragEvidencePolicy: access.admin ? full.ragEvidencePolicy : null,
    flowRunRetentionPolicy: retention ? full.flowRunRetentionPolicy : null,
    spaceTargets: retention ? full.spaceTargets : null,
    flowRunRetentionReviewQueue: access.retentionManage ? full.flowRunRetentionReviewQueue : null,
    flowRetentionHolds: access.retentionHolds ? full.flowRetentionHolds : null,
    holdReviewLimit: retention ? full.holdReviewLimit : null
  };
}

const TABS = [
  "Gallring och bevarande",
  "Uppladdningar och körtider",
  "AI-byggaren",
  "Sparad källtext"
];

const LIMIT_LABEL = "Längsta tid till omprövning (dagar)";

async function expectNoButton(name: RegExp) {
  await expect.element(page.getByRole("button", { name })).not.toBeInTheDocument();
}

async function expectTabs(visible: string[]) {
  for (const name of TABS) {
    const tab = page.getByRole("tab", { name });
    if (visible.includes(name)) await expect.element(tab).toBeVisible();
    else await expect.element(tab).not.toBeInTheDocument();
  }
}

describe("flow settings by retention permission", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listOrganizationFlowRunRetentionReviewQueue.mockResolvedValue(
      pageData().flowRunRetentionReviewQueue
    );
    listFlowRetentionHolds.mockResolvedValue({
      items: [],
      has_more: false,
      review_limit_days: 365
    });
  });

  test("a legal-holds role sees only the retention tab, with holds and no rules", async () => {
    render(FlowSettingsPage, {
      data: dataFor({ admin: false, retentionManage: false, retentionHolds: true }) as never
    });

    await expectTabs(["Gallring och bevarande"]);
    await expect.element(page.getByText("Rättsliga spärrar", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Välj flöde", { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("Organisationens standard").first())
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("Historik som väntar på gallringsgranskning"))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("Oanvända uppladdningar till körningar"))
      .not.toBeInTheDocument();
    await expect.element(page.getByLabelText(LIMIT_LABEL)).not.toBeInTheDocument();
    await expect.element(page.getByRole("button", { name: "Lägg spärr" })).toBeVisible();
    await expectNoButton(/^Spara policy/);
  });

  test("a rules role sees only the retention tab, with rules and no holds", async () => {
    render(FlowSettingsPage, {
      data: dataFor({ admin: false, retentionManage: true, retentionHolds: false }) as never
    });

    await expectTabs(["Gallring och bevarande"]);
    await expect.element(page.getByText("Organisationens standard").first()).toBeVisible();
    await expect.element(page.getByText("Undantag för ytor och flöden")).toBeVisible();
    await expect
      .element(page.getByText("Historik som väntar på gallringsgranskning"))
      .toBeVisible();
    await expect
      .element(page.getByText("Rättsliga spärrar", { exact: true }))
      .not.toBeInTheDocument();
    await expectNoButton(/^Lägg spärr/);
    await expectNoButton(/^Häv/);
    await expectNoButton(/^Ompröva/);
  });

  test("a rules role changes the review limit for legal holds", async () => {
    replaceFlowRetentionHoldReviewLimit.mockResolvedValue({ days: 180, is_default: false });
    render(FlowSettingsPage, {
      data: dataFor({ admin: false, retentionManage: true, retentionHolds: false }) as never
    });

    const field = page.getByLabelText(LIMIT_LABEL);
    await expect.element(field).toHaveValue(365);
    await field.fill("180");
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await vi.waitFor(() =>
      expect(replaceFlowRetentionHoldReviewLimit).toHaveBeenCalledExactlyOnceWith({ days: 180 })
    );
    await field.fill("0");
    await expect.element(page.getByRole("button", { name: "Spara", exact: true })).toBeDisabled();
  });

  test("a role with both retention permissions but no admin sees rules and holds", async () => {
    render(FlowSettingsPage, {
      data: dataFor({ admin: false, retentionManage: true, retentionHolds: true }) as never
    });

    await expectTabs(["Gallring och bevarande"]);
    await expect.element(page.getByText("Organisationens standard").first()).toBeVisible();
    await expect.element(page.getByText("Rättsliga spärrar", { exact: true })).toBeVisible();
    await expect.element(page.getByLabelText(LIMIT_LABEL)).toBeVisible();
  });

  test("an admin without retention permissions keeps every tab and is told what is missing", async () => {
    render(FlowSettingsPage, {
      data: dataFor({ admin: true, retentionManage: false, retentionHolds: false }) as never
    });

    await expectTabs(TABS);
    await expect.element(page.getByText("Gallring kräver egen behörighet")).toBeVisible();
    await expect.element(page.getByText("Oanvända uppladdningar till körningar")).toBeVisible();
    await expect
      .element(page.getByText("Organisationens standard").first())
      .not.toBeInTheDocument();
    await expect.element(page.getByLabelText(LIMIT_LABEL)).not.toBeInTheDocument();
    await expectNoButton(/^Lägg spärr/);
  });

  test("an admin with both retention permissions sees every tab, rules, holds and the limit", async () => {
    render(FlowSettingsPage, {
      data: dataFor({ admin: true, retentionManage: true, retentionHolds: true }) as never
    });

    await expectTabs(TABS);
    await expect.element(page.getByText("Organisationens standard").first()).toBeVisible();
    await expect.element(page.getByText("Rättsliga spärrar", { exact: true })).toBeVisible();
    await expect.element(page.getByLabelText("Längsta tid till omprövning (dagar)")).toBeVisible();
  });
});
