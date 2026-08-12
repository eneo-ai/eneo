import { page, userEvent } from "@vitest/browser/context";
import { EneoError } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import "../../../../app.css";

const getPolicy = vi.hoisted(() => vi.fn());
const getInventory = vi.hoisted(() => vi.fn());
const getMoves = vi.hoisted(() => vi.fn());
const queueMoves = vi.hoisted(() => vi.fn());
const setMovesPaused = vi.hoisted(() => vi.fn());
const replacePolicy = vi.hoisted(() => vi.fn());
const getObjectStoreConnection = vi.hoisted(() => vi.fn());
const createObjectStoreConnection = vi.hoisted(() => vi.fn());
const rotateObjectStoreCredentials = vi.hoisted(() => vi.fn());
const replaceObjectStoreDestination = vi.hoisted(() => vi.fn());
const switchBackObjectStoreDestination = vi.hoisted(() => vi.fn());
const forgetPreviousObjectStoreDestination = vi.hoisted(() => vi.fn());
const abandonPendingObjectStoreDestination = vi.hoisted(() => vi.fn());
// Storage administration is a normal permission, held by the Owner role by
// default. Every editable-state test therefore proves the actual contract:
// an ordinary user carrying the storage permission on one of their roles.
const testUser = vi.hoisted(() => ({ canAdministerStorage: false }));
const invalidate = vi.hoisted(() => vi.fn(async () => {}));

// Every export is listed: other modules in the component graph import
// `replaceState` and friends, and a partial factory breaks their named imports.
vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

vi.mock("$lib/core/AppContext.js", () => ({
  getAppContext: () => ({
    user: {
      roles: testUser.canAdministerStorage ? [{ permissions: ["admin", "storage"] }] : [],
      predefined_roles: []
    }
  })
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    objectContentPolicy: {
      get: getPolicy,
      getInventory,
      getMoves,
      queueMoves,
      setMovesPaused,
      replace: replacePolicy
    },
    objectStoreConnection: {
      get: getObjectStoreConnection,
      create: createObjectStoreConnection,
      rotateCredentials: rotateObjectStoreCredentials,
      replaceDestination: replaceObjectStoreDestination,
      switchBackDestination: switchBackObjectStoreDestination,
      forgetPreviousDestination: forgetPreviousObjectStoreDestination,
      abandonPendingDestination: abandonPendingObjectStoreDestination
    }
  })
}));

vi.mock("$lib/paraglide/messages", async () => {
  const { default: englishMessages } = await import("../../../../../messages/en.json");

  return {
    m: new Proxy<Record<string, unknown>>(
      {},
      {
        get: (_target, key) => {
          const label = String(key);
          return (params?: Record<string, unknown>) => {
            if (label === "storage_settings_target_description")
              return englishMessages.storage_settings_target_description;
            return params ? `${label} ${JSON.stringify(params)}` : label;
          };
        }
      }
    )
  };
});

vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "en"
}));

import StoragePage from "./+page.svelte";

const originalTheme = document.documentElement.dataset.theme;

afterEach(() => {
  if (originalTheme === undefined) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = originalTheme;
});

function policy(overrides: Record<string, unknown> = {}) {
  return {
    policy: {
      revision: 4,
      new_write_storage_target: "postgres_inline",
      session_file_limit_bytes: 20 * 1024 * 1024,
      session_image_limit_bytes: 10 * 1024 * 1024,
      knowledge_file_limit_bytes: 50 * 1024 * 1024,
      transcription_audio_limit_bytes: 100 * 1024 * 1024,
      moves_paused: false,
      updated_by_actor: "storage_admin",
      created_at: "2026-07-25T10:00:00Z",
      updated_at: "2026-07-25T11:00:00Z"
    },
    limits: [
      {
        use_case: "session_file",
        configured_bytes: 20 * 1024 * 1024,
        effective_bytes: 8 * 1024 * 1024,
        storage_target: "postgres_inline",
        operator_ceiling_bytes: 8 * 1024 * 1024,
        constraining_source: "operator_ceiling"
      },
      {
        use_case: "session_image",
        configured_bytes: 10 * 1024 * 1024,
        effective_bytes: 8 * 1024 * 1024,
        storage_target: "postgres_inline",
        operator_ceiling_bytes: 8 * 1024 * 1024,
        constraining_source: "operator_ceiling"
      },
      {
        use_case: "session_audio",
        configured_bytes: 100 * 1024 * 1024,
        effective_bytes: 8 * 1024 * 1024,
        storage_target: "postgres_inline",
        operator_ceiling_bytes: 8 * 1024 * 1024,
        constraining_source: "operator_ceiling"
      },
      {
        use_case: "knowledge_file",
        configured_bytes: 50 * 1024 * 1024,
        effective_bytes: 8 * 1024 * 1024,
        storage_target: "postgres_inline",
        operator_ceiling_bytes: 8 * 1024 * 1024,
        constraining_source: "operator_ceiling"
      },
      {
        use_case: "knowledge_audio",
        configured_bytes: 100 * 1024 * 1024,
        effective_bytes: 8 * 1024 * 1024,
        storage_target: "postgres_inline",
        operator_ceiling_bytes: 8 * 1024 * 1024,
        constraining_source: "operator_ceiling"
      }
    ],
    capabilities: [
      {
        target: "postgres_inline",
        configured: true,
        selectable: true,
        readiness_code: "ready"
      },
      {
        target: "object_store",
        configured: false,
        selectable: false,
        readiness_code: "object_store_not_configured"
      }
    ],
    ...overrides
  };
}

function inventory() {
  return {
    inventory: [
      {
        owner: "file_content",
        target: "postgres_inline",
        state: "available",
        count: 3,
        bytes: 4096,
        oldest_created_at: "2026-07-20T10:00:00Z"
      },
      {
        owner: "knowledge_file",
        target: "object_store",
        state: "available",
        count: 4,
        bytes: 8 * 1024,
        oldest_created_at: "2026-07-19T10:00:00Z"
      },
      {
        owner: "knowledge_file",
        target: "object_store",
        state: "tombstoned",
        count: 2,
        bytes: 16 * 1024,
        oldest_created_at: "2026-07-18T10:00:00Z"
      }
    ],
    postgresql_allocation: {
      total_bytes: 32 * 1024 * 1024,
      inline_content_bytes: 8 * 1024 * 1024,
      searchable_knowledge_bytes: 12 * 1024 * 1024,
      other_bytes: 12 * 1024 * 1024
    }
  };
}

function moves(overrides: Record<string, unknown> = {}) {
  return {
    policy_revision: 4,
    paused: false,
    moves: [
      {
        target: "object_store",
        state: "pending",
        failure_code: null,
        count: 3,
        bytes: 4096,
        oldest_updated_at: "2026-07-21T10:00:00Z"
      }
    ],
    ...overrides
  };
}

function focusElement(element: Element): void {
  if (!(element instanceof HTMLElement)) throw new TypeError("Expected a focusable HTML element");
  element.focus();
}

async function openPreviousDestination(): Promise<void> {
  await page.getByRole("button", { name: "storage_switch_previous_title" }).click();
}

async function openEffectiveLimits(): Promise<void> {
  await page.getByRole("button", { name: "storage_settings_limits_show_technical" }).click();
}

async function openMoveAdvancedSettings(): Promise<void> {
  await page.getByRole("button", { name: "storage_moves_advanced" }).click();
}

async function confirmMoveStart(): Promise<void> {
  await page.getByRole("button", { name: "storage_moves_confirm_action" }).click();
}

async function confirmStorageTargetChange(): Promise<void> {
  await page
    .getByRole("button", {
      name: /storage_settings_confirm_(object_store|postgres)/
    })
    .click();
}

describe("admin storage settings page", () => {
  beforeEach(() => {
    testUser.canAdministerStorage = false;
    getPolicy.mockReset();
    getInventory.mockReset();
    getInventory.mockResolvedValue(inventory());
    getMoves.mockReset();
    getMoves.mockResolvedValue(moves());
    queueMoves.mockReset();
    setMovesPaused.mockReset();
    replacePolicy.mockReset();
    getObjectStoreConnection.mockReset();
    getObjectStoreConnection.mockResolvedValue({
      source: "unconfigured",
      configured: false,
      credentials_can_be_managed: true,
      revision: null,
      endpoint_url: null,
      region: null,
      bucket: null,
      addressing_style: null,
      updated_at: null
    });
    createObjectStoreConnection.mockReset();
    rotateObjectStoreCredentials.mockReset();
    invalidate.mockClear();
  });

  test("shows a loading state before rendering the sanitized deployment policy", async () => {
    let resolvePolicy!: (value: ReturnType<typeof policy>) => void;
    getPolicy.mockImplementation(
      () => new Promise<ReturnType<typeof policy>>((resolve) => (resolvePolicy = resolve))
    );

    render(StoragePage);

    await expect.element(page.getByTestId("storage-loading")).toBeVisible();
    resolvePolicy(policy());

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_title" }))
      .toBeVisible();
    await expect.element(page.getByText("storage_overview_title")).not.toBeInTheDocument();
  });

  test("shows a failed initial read and retries through the same policy owner", async () => {
    getPolicy.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(policy());

    render(StoragePage);

    const loadErrorAlert = page.getByTestId("policy-recovery-alert");
    await expect.element(loadErrorAlert).toBeVisible();
    await expect.element(loadErrorAlert).toHaveFocus();
    await page.getByRole("button", { name: "retry" }).click();

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_target_title" }))
      .toBeVisible();
    expect(getPolicy).toHaveBeenCalledTimes(2);
  });

  test("keeps the deployment policy read-only for an ordinary tenant administrator", async () => {
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect.element(page.getByText("storage_settings_read_only_title")).toBeVisible();
    for (const label of [
      "storage_limit_session_file",
      "storage_limit_session_image",
      "storage_limit_knowledge_file",
      "storage_limit_transcription_audio"
    ]) {
      await expect.element(page.getByText(label, { exact: true })).toBeVisible();
      await expect.element(page.getByLabelText(label)).not.toBeInTheDocument();
    }
    await expect
      .element(page.getByText("20 storage_unit_mb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .not.toBeInTheDocument();
    expect(getInventory).not.toHaveBeenCalled();
    expect(getMoves).not.toHaveBeenCalled();
  });

  test("keeps non-divisible policy byte values exact in read-only and effective projections", async () => {
    const initial = policy();
    getPolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          session_file_limit_bytes: 1025
        },
        limits: initial.limits.map((limit) =>
          limit.use_case === "session_file"
            ? {
                ...limit,
                configured_bytes: 1025,
                effective_bytes: 1025
              }
            : limit
        )
      })
    );

    render(StoragePage);

    const limitsSection = page.getByRole("region", {
      name: "storage_settings_limits_title"
    });
    await expect
      .element(limitsSection.getByText("1,025 storage_unit_b", { exact: true }).first())
      .toBeVisible();
    await openEffectiveLimits();
    await expect
      .element(
        page
          .getByRole("table", { name: "storage_effective_limits_caption" })
          .getByText("1,025 storage_unit_b", { exact: true })
          .first()
      )
      .toBeVisible();
  });

  test("explains knowledge-original routing and shows its effective limits", async () => {
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect.element(page.getByText(/Searchable knowledge stays in PostgreSQL/)).toBeVisible();
    await openEffectiveLimits();
    const limitsTable = page.getByRole("table", {
      name: "storage_effective_limits_caption"
    });
    await expect.element(limitsTable).toBeVisible();
    expect(
      [...limitsTable.element().querySelectorAll("td")].filter(
        (cell) => cell.textContent === "storage_target_not_applicable"
      )
    ).toHaveLength(0);
    expect(
      [...limitsTable.element().querySelectorAll("td")].filter(
        (cell) => cell.textContent === "storage_target_postgres_inline"
      )
    ).toHaveLength(5);
  });

  test("shows localized policy governance metadata and links unavailable storage to its guide", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect.element(page.getByText(/^storage_settings_last_changed/)).toBeVisible();
    await expect
      .element(page.getByRole("link", { name: "storage_settings_object_store_docs" }))
      .toHaveAttribute("href", "https://docs.eneo.ai/guides/object-content-storage");
  });

  test("tests and saves the first connection without changing the storage target", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    createObjectStoreConnection.mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 1,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_add_action" }).click();
    await page.getByLabelText("storage_connection_endpoint").fill("https://objects.example.test");
    await page.getByLabelText("storage_connection_bucket").fill("eneo-content");
    await page.getByLabelText("storage_connection_region").fill("se-1");
    await page.getByLabelText("storage_connection_access_key").fill("access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_save" }).click();

    expect(createObjectStoreConnection).toHaveBeenCalledWith({
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      access_key_id: "access-key",
      secret_access_key: "secret-key",
      addressing_style: "path"
    });
    await expect.element(page.getByText("storage_connection_created_title")).toBeVisible();
    await expect
      .element(page.getByRole("radio", { name: /storage_target_postgres_inline/ }))
      .toBeChecked();
    // Connecting a store flips a capability other pages read from the root
    // layout's settings, so that data has to be reloaded too.
    expect(invalidate).toHaveBeenCalledWith("global:state");
  });

  test("switches to a copied destination and offers switching back", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection.mockReset().mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 1,
      endpoint_url: "https://old.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    });
    replaceObjectStoreDestination.mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 2,
      endpoint_url: "https://new.example.test",
      region: "se-1",
      bucket: "eneo-content-new",
      addressing_style: "path",
      updated_at: "2026-08-06T10:00:00Z",
      previous_destination: {
        revision: 1,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-03T18:00:00Z"
      }
    });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_switch_action" }).click();
    await expect.element(page.getByText("storage_switch_checklist_title")).toBeVisible();
    await page.getByLabelText("storage_connection_endpoint").fill("https://new.example.test");
    await page.getByLabelText("storage_connection_bucket").fill("eneo-content-new");
    await page.getByLabelText("storage_connection_region").fill("se-1");
    await page.getByLabelText("storage_connection_access_key").fill("new-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("new-secret-key");
    await page.getByRole("button", { name: "storage_switch_test_and_switch" }).click();

    expect(replaceObjectStoreDestination).toHaveBeenCalledWith({
      endpoint_url: "https://new.example.test",
      region: "se-1",
      bucket: "eneo-content-new",
      access_key_id: "new-access-key",
      secret_access_key: "new-secret-key",
      addressing_style: "path"
    });
    await expect.element(page.getByText("storage_switch_done_title")).toBeVisible();
    await expect.element(page.getByText("storage_switch_previous_title")).toBeVisible();
    await openPreviousDestination();
    await expect
      .element(page.getByRole("button", { name: "storage_switch_back_action" }))
      .toBeVisible();
  });

  test("tells the administrator to redirect new files before switching", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection.mockReset().mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 1,
      endpoint_url: "https://old.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    });
    replaceObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "Files are still being saved",
        "RESPONSE",
        409,
        0,
        { code: "object_store_new_writes_not_redirected" },
        { endpoint: "POST@/admin/object-store-connection/destination" }
      )
    );

    render(StoragePage);

    await page.getByRole("button", { name: "storage_switch_action" }).click();
    await page.getByLabelText("storage_connection_endpoint").fill("https://new.example.test");
    await page.getByLabelText("storage_connection_bucket").fill("eneo-content-new");
    await page.getByLabelText("storage_connection_region").fill("se-1");
    await page.getByLabelText("storage_connection_access_key").fill("new-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("new-secret-key");
    await page.getByRole("button", { name: "storage_switch_test_and_switch" }).click();

    await expect.element(page.getByText("storage_switch_error_new_writes_title")).toBeVisible();
  });

  test("shows why switching back to the previous destination was refused", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection.mockReset().mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 2,
      endpoint_url: "https://new.example.test",
      region: "se-1",
      bucket: "eneo-content-new",
      addressing_style: "path",
      updated_at: "2026-08-06T10:00:00Z",
      previous_destination: {
        revision: 1,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-03T18:00:00Z"
      }
    });
    switchBackObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "New files still go to object storage",
        "RESPONSE",
        409,
        0,
        { code: "object_store_new_writes_not_redirected" },
        { endpoint: "POST@/admin/object-store-connection/destination/switch-back" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_back_action" }).click();

    // The reason has to be readable on the page: this action never opens the
    // connection dialog where submission errors are rendered.
    await expect.element(page.getByText("storage_switch_error_new_writes_title")).toBeVisible();
  });

  test("shows why removing the previous destination failed", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection.mockReset().mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 2,
      endpoint_url: "https://new.example.test",
      region: "se-1",
      bucket: "eneo-content-new",
      addressing_style: "path",
      updated_at: "2026-08-06T10:00:00Z",
      previous_destination: {
        revision: 1,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-03T18:00:00Z"
      }
    });
    forgetPreviousObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "Connection data is temporarily unavailable",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_database_unavailable" },
        { endpoint: "DELETE@/admin/object-store-connection/previous" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_forget_action" }).click();

    await expect
      .element(page.getByText("storage_connection_error_unavailable_title"))
      .toBeVisible();
  });

  test("renders a committed switch-back whose acknowledgement was lost as done", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        previous_destination: {
          revision: 1,
          endpoint_url: "https://old.example.test",
          region: "se-1",
          bucket: "eneo-content",
          addressing_style: "path",
          updated_at: "2026-08-03T18:00:00Z"
        }
      })
      // The refresh proves the switch-back committed: the previous destination
      // is active again even though the mutation response was lost.
      .mockResolvedValue({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 4,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-06T11:00:00Z",
        previous_destination: {
          revision: 3,
          endpoint_url: "https://new.example.test",
          region: "se-1",
          bucket: "eneo-content-new",
          addressing_style: "path",
          updated_at: "2026-08-06T10:00:00Z"
        }
      });
    switchBackObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "The save result could not be confirmed",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_mutation_outcome_unknown" },
        { endpoint: "POST@/admin/object-store-connection/destination/switch-back" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_back_action" }).click();

    // The committed cutover must render as done, not as a retryable failure
    // that would invite reversing it.
    await expect.element(page.getByText("storage_switch_back_done_title")).toBeVisible();
    await expect
      .element(page.getByText("storage_switch_outcome_not_applied_title"))
      .not.toBeInTheDocument();
  });

  test("reports an unconfirmed switch-back that never applied and allows retry", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection.mockReset().mockResolvedValue({
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 2,
      endpoint_url: "https://new.example.test",
      region: "se-1",
      bucket: "eneo-content-new",
      addressing_style: "path",
      updated_at: "2026-08-06T10:00:00Z",
      previous_destination: {
        revision: 1,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-03T18:00:00Z"
      }
    });
    switchBackObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "The save result could not be confirmed",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_mutation_outcome_unknown" },
        { endpoint: "POST@/admin/object-store-connection/destination/switch-back" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_back_action" }).click();

    await expect.element(page.getByText("storage_switch_outcome_not_applied_title")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "storage_switch_back_action" }))
      .toBeEnabled();
  });

  test("reconciles a committed switch-back whose transport failed without a response", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        previous_destination: {
          revision: 1,
          endpoint_url: "https://old.example.test",
          region: "se-1",
          bucket: "eneo-content",
          addressing_style: "path",
          updated_at: "2026-08-03T18:00:00Z"
        }
      })
      .mockResolvedValue({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 4,
        endpoint_url: "https://old.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-06T11:00:00Z",
        previous_destination: {
          revision: 3,
          endpoint_url: "https://new.example.test",
          region: "se-1",
          bucket: "eneo-content-new",
          addressing_style: "path",
          updated_at: "2026-08-06T10:00:00Z"
        }
      });
    // The browser never received a response: no status, no error code. The
    // server may still have committed the cutover.
    switchBackObjectStoreDestination.mockRejectedValue(
      new EneoError("Failed to fetch", "CONNECTION", 0, 0, "No response text", {
        endpoint: "POST@/admin/object-store-connection/destination/switch-back"
      })
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_back_action" }).click();

    // The refresh proves the cutover committed; it must not be offered as a
    // retryable failure whose retry would reverse it.
    await expect.element(page.getByText("storage_switch_back_done_title")).toBeVisible();
    await expect
      .element(page.getByText("storage_connection_error_unavailable_title"))
      .not.toBeInTheDocument();
  });

  test("shows divergence when the archive changed under an unconfirmed switch-back", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        previous_destination: {
          revision: 1,
          endpoint_url: "https://old.example.test",
          region: "se-1",
          bucket: "eneo-content",
          addressing_style: "path",
          updated_at: "2026-08-03T18:00:00Z"
        }
      })
      // A concurrent administrator replaced the archive: same destinations,
      // but the archived row is a different revision.
      .mockResolvedValue({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 4,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T11:00:00Z",
        previous_destination: {
          revision: 3,
          endpoint_url: "https://old.example.test",
          region: "se-1",
          bucket: "eneo-content",
          addressing_style: "path",
          updated_at: "2026-08-06T11:00:00Z"
        }
      });
    switchBackObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "The save result could not be confirmed",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_mutation_outcome_unknown" },
        { endpoint: "POST@/admin/object-store-connection/destination/switch-back" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_back_action" }).click();

    await expect.element(page.getByText("storage_connection_error_conflict_title")).toBeVisible();
    await expect
      .element(page.getByText("storage_switch_outcome_not_applied_title"))
      .not.toBeInTheDocument();
  });

  test("lets the administrator abandon a pending destination attempt", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://objects.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        pending_destination: {
          revision: 3,
          endpoint_url: "https://stuck.example.test",
          region: "se-1",
          bucket: "eneo-content-stuck",
          addressing_style: "path",
          updated_at: "2026-08-06T09:00:00Z"
        }
      })
      .mockResolvedValue({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://objects.example.test",
        region: "se-1",
        bucket: "eneo-content",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        pending_destination: null
      });
    abandonPendingObjectStoreDestination.mockReset().mockResolvedValue(undefined);

    render(StoragePage);

    await expect.element(page.getByText("storage_pending_title")).toBeVisible();
    await page.getByRole("button", { name: "storage_pending_abandon_action" }).click();

    expect(abandonPendingObjectStoreDestination).toHaveBeenCalledWith(3);
    await expect.element(page.getByText("storage_pending_title")).not.toBeInTheDocument();
  });

  test("shows divergence when a lost abandon response hides a replaced attempt", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const base = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 2,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-06T10:00:00Z"
    };
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        ...base,
        pending_destination: {
          revision: 3,
          endpoint_url: "https://stuck.example.test",
          region: "se-1",
          bucket: "eneo-content-stuck",
          addressing_style: "path",
          updated_at: "2026-08-06T09:00:00Z"
        }
      })
      // The reconciling refresh fails too; the captured revision must
      // survive it.
      .mockRejectedValueOnce(new Error("offline"))
      // While the response was lost, a newer attempt claimed the slot.
      .mockResolvedValue({
        ...base,
        pending_destination: {
          revision: 5,
          endpoint_url: "https://stuck.example.test",
          region: "se-1",
          bucket: "eneo-content-stuck",
          addressing_style: "path",
          updated_at: "2026-08-06T09:30:00Z"
        }
      });
    abandonPendingObjectStoreDestination.mockReset().mockRejectedValue(
      new EneoError("Failed to fetch", "CONNECTION", 0, 0, "No response text", {
        endpoint: "DELETE@/admin/object-store-connection/pending"
      })
    );

    render(StoragePage);

    await page.getByRole("button", { name: "storage_pending_abandon_action" }).click();

    // The failed refresh leaves the load-error recovery path; retrying it
    // resumes the SAME reconciliation against the captured revision.
    await expect.element(page.getByText("storage_connection_load_error_title")).toBeVisible();
    await page.getByRole("button", { name: "retry" }).click();

    // The click must not silently transfer to the newer attempt.
    await expect.element(page.getByText("storage_connection_error_conflict_title")).toBeVisible();
    expect(abandonPendingObjectStoreDestination).toHaveBeenCalledTimes(1);
  });

  test("renders a committed forget whose acknowledgement was lost as done", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        previous_destination: {
          revision: 1,
          endpoint_url: "https://old.example.test",
          region: "se-1",
          bucket: "eneo-content",
          addressing_style: "path",
          updated_at: "2026-08-03T18:00:00Z"
        }
      })
      .mockResolvedValue({
        source: "admin",
        configured: true,
        credentials_can_be_managed: true,
        revision: 2,
        endpoint_url: "https://new.example.test",
        region: "se-1",
        bucket: "eneo-content-new",
        addressing_style: "path",
        updated_at: "2026-08-06T10:00:00Z",
        previous_destination: null
      });
    forgetPreviousObjectStoreDestination.mockRejectedValue(
      new EneoError(
        "The save result could not be confirmed",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_mutation_outcome_unknown" },
        { endpoint: "DELETE@/admin/object-store-connection/previous" }
      )
    );

    render(StoragePage);

    await openPreviousDestination();
    await page.getByRole("button", { name: "storage_switch_forget_action" }).click();

    await expect
      .element(page.getByRole("button", { name: "storage_switch_back_action" }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("storage_switch_outcome_not_applied_title"))
      .not.toBeInTheDocument();
  });

  test("reloads the existing connection after a setup conflict", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const configuredConnection = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 1,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    } as const;
    getObjectStoreConnection
      .mockReset()
      .mockResolvedValueOnce({
        source: "unconfigured",
        configured: false,
        credentials_can_be_managed: true,
        revision: null,
        endpoint_url: null,
        region: null,
        bucket: null,
        addressing_style: null,
        updated_at: null
      })
      .mockResolvedValueOnce(configuredConnection);
    createObjectStoreConnection.mockRejectedValue(
      new EneoError(
        "Object storage is already configured",
        "RESPONSE",
        409,
        0,
        { code: "object_store_connection_already_configured" },
        { endpoint: "POST@/admin/object-store-connection" }
      )
    );

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_add_action" }).click();
    await page.getByLabelText("storage_connection_endpoint").fill("https://objects.example.test");
    await page.getByLabelText("storage_connection_bucket").fill("eneo-content");
    await page.getByLabelText("storage_connection_region").fill("se-1");
    await page.getByLabelText("storage_connection_access_key").fill("access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_save" }).click();

    await expect
      .element(page.getByText("storage_connection_already_configured_title"))
      .toBeVisible();
    await expect
      .element(page.getByRole("heading", { name: "storage_connection_dialog_create_title" }))
      .not.toBeInTheDocument();
    await expect.element(page.getByText("https://objects.example.test")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "storage_connection_add_action" }))
      .not.toBeInTheDocument();
    expect(getObjectStoreConnection).toHaveBeenCalledTimes(2);
    expect(getPolicy).toHaveBeenCalledTimes(2);
  });

  test("keeps the previous-destination controls after rotating credentials", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const archived = {
      revision: 1,
      endpoint_url: "https://old.example.test",
      region: "se-1",
      bucket: "eneo-content-old",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    } as const;
    const connection = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 3,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z",
      previous_destination: archived
    } as const;
    getObjectStoreConnection.mockReset().mockResolvedValue(connection);
    // Rotation leaves the archive in place, so its response carries it too.
    rotateObjectStoreCredentials.mockResolvedValue({
      ...connection,
      revision: 4,
      previous_destination: archived
    });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_rotate_action" }).click();
    await page.getByLabelText("storage_connection_access_key").fill("new-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("new-secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_rotate" }).click();

    await expect.element(page.getByText("storage_connection_rotated_title")).toBeVisible();
    await openPreviousDestination();
    // The recovery controls must survive a rotation: the page does not
    // reload the connection after a successful save.
    await expect
      .element(page.getByRole("button", { name: "storage_switch_back_action" }))
      .toBeVisible();
  });

  test("replaces the complete key pair without presenting the destination as editable", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const connection = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 3,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    } as const;
    getObjectStoreConnection.mockResolvedValue(connection);
    rotateObjectStoreCredentials.mockResolvedValue({ ...connection, revision: 4 });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_rotate_action" }).click();

    await expect.element(page.getByText("storage_connection_current_destination")).toBeVisible();
    await expect
      .element(page.getByText("storage_connection_destination_locked_help"))
      .toBeVisible();
    await expect
      .element(page.getByLabelText("storage_connection_endpoint"))
      .not.toBeInTheDocument();
    await expect.element(page.getByLabelText("storage_connection_bucket")).not.toBeInTheDocument();

    await page.getByLabelText("storage_connection_access_key").fill("replacement-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("replacement-secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_rotate" }).click();

    expect(rotateObjectStoreCredentials).toHaveBeenCalledWith({
      expected_revision: 3,
      access_key_id: "replacement-access-key",
      secret_access_key: "replacement-secret-key"
    });
  });

  test("reloads the connection revision after a concurrent credential rotation", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const connection = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 3,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    } as const;
    let rejectConnectionReload!: (reason: unknown) => void;
    getObjectStoreConnection
      .mockResolvedValueOnce(connection)
      .mockImplementationOnce(
        () =>
          new Promise<never>((_resolve, reject) => {
            rejectConnectionReload = reject;
          })
      )
      .mockResolvedValueOnce({ ...connection, revision: 4 });
    rotateObjectStoreCredentials
      .mockRejectedValueOnce(
        new EneoError(
          "The connection changed while it was being tested",
          "RESPONSE",
          409,
          0,
          { code: "object_store_connection_revision_conflict" },
          { endpoint: "PUT@/admin/object-store-connection/credentials" }
        )
      )
      .mockResolvedValueOnce({ ...connection, revision: 5 });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_rotate_action" }).click();
    await page.getByLabelText("storage_connection_access_key").fill("stale-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("stale-secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_rotate" }).click();

    await expect
      .element(page.getByRole("heading", { name: "storage_connection_dialog_rotate_title" }))
      .not.toBeInTheDocument();
    expect(getObjectStoreConnection).toHaveBeenCalledTimes(2);
    await expect
      .element(page.getByText("storage_connection_error_conflict_title"))
      .not.toBeInTheDocument();

    rejectConnectionReload(new Error("connection reload failed"));

    await expect.element(page.getByText("storage_connection_load_error_title")).toBeVisible();
    await expect
      .element(page.getByText("storage_connection_error_conflict_title"))
      .not.toBeInTheDocument();

    await page.getByRole("button", { name: "retry" }).click();

    await expect.element(page.getByText("storage_connection_error_conflict_title")).toBeVisible();

    await page.getByRole("button", { name: "storage_connection_rotate_action" }).click();
    await expect.element(page.getByLabelText("storage_connection_access_key")).toHaveValue("");
    await expect.element(page.getByLabelText("storage_connection_secret_key")).toHaveValue("");
    await page.getByLabelText("storage_connection_access_key").fill("current-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("current-secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_rotate" }).click();

    expect(rotateObjectStoreCredentials).toHaveBeenNthCalledWith(2, {
      expected_revision: 4,
      access_key_id: "current-access-key",
      secret_access_key: "current-secret-key"
    });
    expect(getObjectStoreConnection).toHaveBeenCalledTimes(3);
    expect(getPolicy).toHaveBeenCalledTimes(3);
  });

  test("finishes connection and policy recovery when an uncertain save needs a retry", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const connection = {
      source: "admin",
      configured: true,
      credentials_can_be_managed: true,
      revision: 3,
      endpoint_url: "https://objects.example.test",
      region: "se-1",
      bucket: "eneo-content",
      addressing_style: "path",
      updated_at: "2026-08-03T18:00:00Z"
    } as const;
    getObjectStoreConnection
      .mockResolvedValueOnce(connection)
      .mockRejectedValueOnce(new Error("connection reload failed"))
      .mockResolvedValueOnce({ ...connection, revision: 4 });
    rotateObjectStoreCredentials.mockRejectedValue(
      new EneoError(
        "The database could not confirm the save",
        "RESPONSE",
        503,
        0,
        { code: "object_store_connection_mutation_outcome_unknown" },
        { endpoint: "PUT@/admin/object-store-connection/credentials" }
      )
    );

    render(StoragePage);

    await page.getByRole("button", { name: "storage_connection_rotate_action" }).click();
    await page.getByLabelText("storage_connection_access_key").fill("replacement-access-key");
    await page.getByLabelText("storage_connection_secret_key").fill("replacement-secret-key");
    await page.getByRole("button", { name: "storage_connection_test_and_rotate" }).click();

    await expect
      .element(page.getByText("storage_connection_mutation_outcome_unknown_title"))
      .toBeVisible();
    await expect
      .element(page.getByRole("heading", { name: "storage_connection_dialog_rotate_title" }))
      .not.toBeInTheDocument();
    expect(getObjectStoreConnection).toHaveBeenCalledTimes(2);

    await page.getByRole("button", { name: "retry" }).click();

    await expect
      .element(page.getByText("https://objects.example.test", { exact: true }))
      .toBeVisible();
    expect(getObjectStoreConnection).toHaveBeenCalledTimes(3);
    expect(getPolicy).toHaveBeenCalledTimes(2);
  });

  test("refreshes policy, move progress, and inventory from the page status action", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect.element(page.getByText("storage_move_state_pending")).toBeVisible();
    const refreshButton = page.getByRole("button", { name: "storage_settings_refresh_status" });
    await refreshButton.click();

    expect(getPolicy).toHaveBeenCalledTimes(2);
    expect(getMoves).toHaveBeenCalledTimes(2);
    expect(getInventory).toHaveBeenCalledTimes(2);
    await expect.element(refreshButton).toHaveFocus();
  });

  test("locks policy inputs while a refresh is awaiting its response", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    let resolveRefresh!: (value: ReturnType<typeof policy>) => void;
    getPolicy
      .mockResolvedValueOnce(initial)
      .mockImplementationOnce(
        () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveRefresh = resolve))
      );

    render(StoragePage);

    const target = page.getByRole("radio", { name: /storage_target_postgres_inline/ });
    const limitInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    const refreshClick = (async () => {
      await page.getByRole("button", { name: "storage_settings_refresh_status" }).click();
    })();

    await expect.element(target).toBeDisabled();
    await expect.element(limitInput).toBeDisabled();
    await expect.element(limitInput).toHaveValue(20);

    resolveRefresh(initial);
    await refreshClick;

    await expect.element(target).toBeEnabled();
    await expect.element(limitInput).toBeEnabled();
    await expect.element(limitInput).toHaveValue(20);
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("blocks policy mutations while preserving a draft during refresh", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    let resolveRefresh!: (value: ReturnType<typeof policy>) => void;
    getPolicy
      .mockResolvedValueOnce(initial)
      .mockImplementationOnce(
        () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveRefresh = resolve))
      );

    render(StoragePage);

    const limitInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await limitInput.fill("30");
    const refreshClick = (async () => {
      await page.getByRole("button", { name: "storage_settings_refresh_status" }).click();
    })();

    const saveButton = page.getByRole("button", { name: "storage_settings_save" });
    const discardButton = page.getByRole("button", { name: "discard_changes" });
    const pauseButton = page.getByRole("button", { name: "storage_moves_pause" });
    await expect.element(limitInput).toBeDisabled();
    await expect.element(saveButton).toBeDisabled();
    await expect.element(discardButton).toBeDisabled();
    await expect.element(pauseButton).toBeDisabled();
    for (const control of [saveButton, pauseButton]) {
      const element = control.element();
      if (!(element instanceof HTMLButtonElement)) {
        throw new TypeError("Expected policy mutation control to be a button");
      }
      element.click();
    }
    expect(replacePolicy).not.toHaveBeenCalled();
    expect(setMovesPaused).not.toHaveBeenCalled();

    resolveRefresh(initial);
    await refreshClick;

    await expect.element(limitInput).toBeEnabled();
    await expect.element(limitInput).toHaveValue(30);
    await expect.element(saveButton).toBeEnabled();
    await expect.element(pauseButton).toBeEnabled();
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("does not refresh policy while a limit save is awaiting its response", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    const committed = policy({
      policy: {
        ...initial.policy,
        revision: 5,
        session_file_limit_bytes: 30 * 1024 * 1024
      }
    });
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(committed);
    let resolveReplacement!: (value: ReturnType<typeof policy>) => void;
    replacePolicy.mockImplementation(
      () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveReplacement = resolve))
    );

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    const refreshButton = page.getByRole("button", { name: "storage_settings_refresh_status" });
    await expect.element(refreshButton).toHaveAttribute("aria-disabled", "true");
    const refreshElement = refreshButton.element();
    if (!(refreshElement instanceof HTMLButtonElement)) {
      throw new TypeError("Expected the refresh control to be a button");
    }
    refreshElement.click();
    expect(getPolicy).toHaveBeenCalledTimes(1);

    resolveReplacement(committed);

    await expect.element(page.getByText("storage_settings_no_changes")).toBeVisible();
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("does not refresh policy while a pause is awaiting its response", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    const committed = policy({
      policy: {
        ...initial.policy,
        revision: 5,
        moves_paused: true
      }
    });
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(committed);
    let resolvePause!: (value: { policy_revision: number; paused: boolean }) => void;
    setMovesPaused.mockImplementation(
      () =>
        new Promise<{ policy_revision: number; paused: boolean }>(
          (resolve) => (resolvePause = resolve)
        )
    );

    render(StoragePage);

    const limitInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await limitInput.fill("30");
    const pauseClick = (async () => {
      await page.getByRole("button", { name: "storage_moves_pause" }).click();
    })();

    const refreshButton = page.getByRole("button", { name: "storage_settings_refresh_status" });
    await expect.element(refreshButton).toHaveAttribute("aria-disabled", "true");
    const refreshElement = refreshButton.element();
    if (!(refreshElement instanceof HTMLButtonElement)) {
      throw new TypeError("Expected the refresh control to be a button");
    }
    refreshElement.click();
    expect(getPolicy).toHaveBeenCalledTimes(1);

    resolvePause({ policy_revision: 5, paused: true });
    await pauseClick;

    await expect.element(limitInput).toHaveValue(30);
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("formats storage counts and binary byte units with the active locale", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getMoves.mockResolvedValue(
      moves({
        moves: [
          {
            target: "object_store",
            state: "pending",
            failure_code: null,
            count: 1234,
            bytes: 4096,
            oldest_updated_at: "2026-07-21T10:00:00Z"
          }
        ]
      })
    );

    render(StoragePage);

    await expect.element(page.getByText("1,234", { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("4 storage_unit_kb", { exact: true }).first())
      .toBeVisible();
  });

  test("queues a bounded page and pauses or resumes through revision-fenced commands", async () => {
    testUser.canAdministerStorage = true;
    const loadedPolicy = policy();
    const initial = policy({
      policy: {
        ...loadedPolicy.policy,
        new_write_storage_target: "object_store"
      },
      capabilities: [
        {
          target: "postgres_inline",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        },
        {
          target: "object_store",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        }
      ]
    });
    getPolicy.mockResolvedValue(initial);
    queueMoves.mockResolvedValue({ queued_count: 3, target_too_large_count: 1 });
    setMovesPaused
      .mockResolvedValueOnce({ policy_revision: 5, paused: true })
      .mockResolvedValueOnce({ policy_revision: 6, paused: false });

    render(StoragePage);

    await expect.element(page.getByRole("heading", { name: "storage_moves_title" })).toBeVisible();
    await expect.element(page.getByText("storage_move_state_pending")).toBeVisible();
    await expect
      .element(page.getByLabelText("storage_moves_target"))
      .toHaveTextContent("storage_target_object_store");
    await openMoveAdvancedSettings();
    await page.getByLabelText("storage_moves_limit").fill("7");
    const queueButton = page.getByRole("button", { name: "storage_moves_queue" });
    await queueButton.click();
    await confirmMoveStart();

    expect(queueMoves).toHaveBeenCalledWith({ target: "object_store", limit: 7 });
    await expect.element(page.getByText(/storage_moves_queue_result/)).toBeVisible();
    await expect.element(queueButton).toHaveFocus();

    await page.getByRole("button", { name: "storage_moves_pause" }).click();
    expect(setMovesPaused).toHaveBeenNthCalledWith(1, {
      expected_revision: 4,
      moves_paused: true
    });
    await page.getByRole("button", { name: "storage_moves_resume" }).click();
    expect(setMovesPaused).toHaveBeenNthCalledWith(2, {
      expected_revision: 5,
      moves_paused: false
    });
  });

  test("pauses and resumes moves when the queue is empty", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getMoves.mockResolvedValue(moves({ moves: [] }));
    setMovesPaused
      .mockResolvedValueOnce({ policy_revision: 5, paused: true })
      .mockResolvedValueOnce({ policy_revision: 6, paused: false });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_moves_pause" }).click();
    expect(setMovesPaused).toHaveBeenNthCalledWith(1, {
      expected_revision: 4,
      moves_paused: true
    });

    await page.getByRole("button", { name: "storage_moves_resume" }).click();
    expect(setMovesPaused).toHaveBeenNthCalledWith(2, {
      expected_revision: 5,
      moves_paused: false
    });
  });

  test("queues moves to PostgreSQL while object storage is unavailable", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    queueMoves.mockResolvedValue({ queued_count: 1, target_too_large_count: 0 });

    render(StoragePage);

    await page.getByLabelText("storage_moves_target").click();
    await page.getByRole("option", { name: "storage_target_postgres_inline" }).click();
    const queueButton = page.getByRole("button", { name: "storage_moves_queue" });
    await expect.element(queueButton).toBeEnabled();
    await queueButton.click();
    await confirmMoveStart();

    expect(queueMoves).toHaveBeenCalledWith({ target: "postgres_inline", limit: 25 });
  });

  test("defaults the move destination to the current policy target", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect
      .element(page.getByLabelText("storage_moves_target"))
      .toHaveTextContent("storage_target_postgres_inline");
  });

  test("shows progress only on the move action that is running", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(
      policy({
        capabilities: [
          {
            target: "postgres_inline",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          },
          {
            target: "object_store",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          }
        ]
      })
    );
    let resolvePause!: (value: { policy_revision: number; paused: boolean }) => void;
    setMovesPaused.mockImplementation(
      () =>
        new Promise<{ policy_revision: number; paused: boolean }>((resolve) => {
          resolvePause = resolve;
        })
    );

    render(StoragePage);

    const queueButton = page.getByRole("button", { name: "storage_moves_queue" });
    const pauseButton = page.getByRole("button", { name: "storage_moves_pause" });
    const clickPause = (async () => {
      await pauseButton.click();
    })();

    await expect.element(queueButton).toBeDisabled();
    expect(pauseButton.element().hasAttribute("disabled")).toBe(false);
    await expect.element(pauseButton).toHaveAttribute("aria-disabled", "true");
    await expect.element(queueButton).toHaveAttribute("aria-busy", "false");
    await expect.element(pauseButton).toHaveAttribute("aria-busy", "true");
    expect(queueButton.element().querySelector('[data-icon="inline-start"]')).toBeNull();
    expect(pauseButton.element().querySelector('[data-icon="inline-start"]')).not.toBeNull();

    resolvePause({ policy_revision: 5, paused: true });
    await clickPause;
    const resumeButton = page.getByRole("button", { name: "storage_moves_resume" });
    await expect.element(resumeButton).toBeEnabled();
    await expect.element(resumeButton).toHaveFocus();
  });

  test("locks policy inputs while pause recovery is pending", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_image_limit_bytes: 12 * 1024 * 1024,
          moves_paused: true
        }
      })
    );
    getMoves
      .mockResolvedValueOnce(moves())
      .mockResolvedValueOnce(moves({ policy_revision: 5, paused: true }));
    let rejectPause!: (reason: unknown) => void;
    setMovesPaused.mockImplementation(
      () =>
        new Promise<{ policy_revision: number; paused: boolean }>((_resolve, reject) => {
          rejectPause = reject;
        })
    );

    render(StoragePage);

    const target = page.getByRole("radio", { name: /storage_target_postgres_inline/ });
    const limits = [
      page.getByLabelText("storage_limit_session_file", { exact: true }),
      page.getByLabelText("storage_limit_session_image", { exact: true }),
      page.getByLabelText("storage_limit_knowledge_file", { exact: true }),
      page.getByLabelText("storage_limit_transcription_audio", { exact: true })
    ];
    await expect.element(target).toBeEnabled();
    const pause = (async () => {
      await page.getByRole("button", { name: "storage_moves_pause" }).click();
    })();

    await expect.element(target).toBeDisabled();
    for (const limit of limits) await expect.element(limit).toBeDisabled();
    await expect.element(limits[0]).toHaveValue(20);

    rejectPause(new Error("response lost"));
    await pause;
    await expect.element(page.getByText("storage_moves_outcome_unknown_title")).toBeVisible();
    await expect.element(target).toBeEnabled();
    for (const limit of limits) await expect.element(limit).toBeEnabled();
    await expect.element(limits[1]).toHaveValue(12);
  });

  test("keeps the selected destination and limit when readiness rejects queueing", async () => {
    testUser.canAdministerStorage = true;
    const loadedPolicy = policy();
    getPolicy.mockResolvedValue(
      policy({
        policy: {
          ...loadedPolicy.policy,
          new_write_storage_target: "object_store"
        },
        capabilities: [
          {
            target: "postgres_inline",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          },
          {
            target: "object_store",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          }
        ]
      })
    );
    queueMoves.mockRejectedValue({ status: 503 });

    render(StoragePage);

    const target = page.getByLabelText("storage_moves_target");
    await openMoveAdvancedSettings();
    const limit = page.getByLabelText("storage_moves_limit");
    await limit.fill("7");
    await page.getByRole("button", { name: "storage_moves_queue" }).click();
    await confirmMoveStart();

    await expect.element(page.getByText("storage_moves_action_error_title")).toBeVisible();
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    await expect.element(page.getByTestId("move-recovery-alert")).toHaveFocus();
    await expect.element(target).toHaveTextContent("storage_target_object_store");
    await expect.element(limit).toHaveValue(7);
    expect(queueMoves).toHaveBeenCalledTimes(1);
  });

  test("reloads committed queue progress when the command outcome is unknown", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(
      policy({
        capabilities: [
          {
            target: "postgres_inline",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          },
          {
            target: "object_store",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          }
        ]
      })
    );
    let resolveReload!: (value: ReturnType<typeof moves>) => void;
    getMoves
      .mockResolvedValueOnce(moves())
      .mockImplementationOnce(
        () => new Promise<ReturnType<typeof moves>>((resolve) => (resolveReload = resolve))
      );
    queueMoves.mockRejectedValue(new Error("response lost"));

    render(StoragePage);

    const queueButton = page.getByRole("button", { name: "storage_moves_queue" });
    const pauseButton = page.getByRole("button", { name: "storage_moves_pause" });
    await expect.element(page.getByText("storage_move_state_pending")).toBeVisible();
    await queueButton.click();
    const clickQueue = (async () => {
      await page.getByRole("button", { name: "storage_moves_confirm_action" }).click();
    })();

    await expect.element(page.getByText("storage_move_state_pending")).toBeVisible();
    await expect.element(queueButton).toHaveAttribute("aria-disabled", "true");
    await expect.element(pauseButton).toBeDisabled();
    resolveReload(
      moves({
        policy_revision: 5,
        moves: [
          {
            target: "object_store",
            state: "pending",
            failure_code: null,
            count: 4,
            bytes: 8192,
            oldest_updated_at: "2026-07-21T10:00:00Z"
          }
        ]
      })
    );
    await clickQueue;

    await expect.element(page.getByText("storage_moves_outcome_unknown_title")).toBeVisible();
    await expect
      .element(
        page.getByRole("region", { name: "storage_moves_title" }).getByText("4", { exact: true })
      )
      .toBeVisible();
  });

  test("keeps a dirty draft on its old baseline after a committed pause response is lost", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_image_limit_bytes: 12 * 1024 * 1024,
          moves_paused: true
        }
      })
    );
    getMoves
      .mockResolvedValueOnce(moves())
      .mockResolvedValueOnce(moves({ policy_revision: 5, paused: true }));
    setMovesPaused.mockRejectedValue(new Error("response lost"));
    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    await page.getByRole("button", { name: "storage_moves_pause" }).click();
    await expect.element(page.getByText("storage_moves_outcome_unknown_title")).toBeVisible();
    await expect.element(page.getByText("storage_settings_stale_title")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "storage_moves_resume" })).toBeEnabled();
    await expect
      .element(page.getByLabelText("storage_limit_session_file", { exact: true }))
      .toHaveValue(30);
    await expect
      .element(page.getByLabelText("storage_limit_session_image", { exact: true }))
      .toHaveValue(10);
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .toBeDisabled();
    expect(replacePolicy).not.toHaveBeenCalled();
  });

  test("keeps the full policy revision as the replacement baseline", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValue(initial);
    getMoves.mockResolvedValue(moves({ policy_revision: 5, paused: true }));
    replacePolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_file_limit_bytes: 30 * 1024 * 1024
        }
      })
    );

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    expect(replacePolicy).toHaveBeenCalledWith(expect.objectContaining({ expected_revision: 4 }));
  });

  test("refreshes the full policy after pausing from a newer move projection", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(
      policy({
        policy: {
          ...initial.policy,
          revision: 6,
          session_image_limit_bytes: 12 * 1024 * 1024,
          moves_paused: true
        }
      })
    );
    getMoves
      .mockResolvedValueOnce(moves({ policy_revision: 5 }))
      .mockResolvedValueOnce(moves({ policy_revision: 6, paused: true }));
    setMovesPaused.mockResolvedValue({ policy_revision: 6, paused: true });
    replacePolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          revision: 7,
          session_file_limit_bytes: 30 * 1024 * 1024,
          session_image_limit_bytes: 12 * 1024 * 1024,
          moves_paused: true
        }
      })
    );

    render(StoragePage);

    await page.getByRole("button", { name: "storage_moves_pause" }).click();
    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    expect(replacePolicy).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_revision: 6,
        session_image_limit_bytes: 12 * 1024 * 1024
      })
    );
  });

  test("serializes policy saves and pause commands on their shared revision", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValue(initial);
    let resolveSave!: (value: ReturnType<typeof policy>) => void;
    replacePolicy.mockImplementation(
      () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveSave = resolve))
    );
    let resolvePause!: (value: { policy_revision: number; paused: boolean }) => void;
    setMovesPaused.mockImplementation(
      () =>
        new Promise<{ policy_revision: number; paused: boolean }>((resolve) => {
          resolvePause = resolve;
        })
    );

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    const saveButton = page.getByRole("button", { name: "storage_settings_save" });
    const pauseButton = page.getByRole("button", { name: "storage_moves_pause" });
    const saveClick = (async () => {
      await saveButton.click();
    })();

    await expect.element(pauseButton).toBeDisabled();
    resolveSave(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_file_limit_bytes: 30 * 1024 * 1024
        }
      })
    );
    await saveClick;

    await page.getByLabelText("storage_limit_session_image", { exact: true }).fill("11");
    await expect.element(saveButton).toBeEnabled();
    const pauseClick = (async () => {
      await pauseButton.click();
    })();

    await expect.element(saveButton).toBeDisabled();
    resolvePause({ policy_revision: 6, paused: true });
    await pauseClick;
    await expect.element(saveButton).toBeEnabled();
  });

  test("uses the saved policy revision and pause state for the next move command", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValue(initial);
    replacePolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_file_limit_bytes: 30 * 1024 * 1024,
          moves_paused: true
        }
      })
    );
    setMovesPaused.mockResolvedValue({ policy_revision: 6, paused: false });

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    await page.getByRole("button", { name: "storage_settings_save" }).click();
    await page.getByRole("button", { name: "storage_moves_resume" }).click();

    expect(setMovesPaused).toHaveBeenCalledWith({
      expected_revision: 5,
      moves_paused: false
    });
  });

  test("keeps a newer move projection when an older full policy response finishes later", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy({
      capabilities: [
        {
          target: "postgres_inline",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        },
        {
          target: "object_store",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        }
      ]
    });
    getPolicy.mockResolvedValue(initial);
    getMoves
      .mockResolvedValueOnce(moves())
      .mockResolvedValueOnce(moves({ policy_revision: 6, paused: true }));
    let resolveSave!: (value: ReturnType<typeof policy>) => void;
    replacePolicy.mockImplementation(
      () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveSave = resolve))
    );
    queueMoves.mockResolvedValue({ queued_count: 1, target_too_large_count: 0 });
    setMovesPaused.mockResolvedValue({ policy_revision: 7, paused: false });

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    const save = (async () => {
      await page.getByRole("button", { name: "storage_settings_save" }).click();
    })();
    await expect.element(page.getByRole("button", { name: "storage_moves_pause" })).toBeDisabled();
    await page.getByRole("button", { name: "storage_moves_queue" }).click();
    await confirmMoveStart();
    resolveSave(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          session_file_limit_bytes: 30 * 1024 * 1024
        }
      })
    );
    await save;
    await page.getByRole("button", { name: "storage_moves_resume" }).click();

    expect(setMovesPaused).toHaveBeenCalledWith({
      expected_revision: 6,
      moves_paused: false
    });
  });

  test("disables moves toward object storage while it is unavailable", async () => {
    testUser.canAdministerStorage = true;
    const loadedPolicy = policy();
    getPolicy.mockResolvedValue(
      policy({
        policy: {
          ...loadedPolicy.policy,
          new_write_storage_target: "object_store"
        }
      })
    );

    render(StoragePage);

    await expect.element(page.getByRole("button", { name: "storage_moves_queue" })).toBeDisabled();
    await expect
      .element(page.getByText("storage_moves_store_unavailable", { exact: true }))
      .toBeVisible();
    expect(queueMoves).not.toHaveBeenCalled();
  });

  test("recovers a scoped move-progress failure without reloading policy or inventory", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getMoves.mockRejectedValueOnce(new Error("progress unavailable"));

    render(StoragePage);

    const moveErrorAlert = page.getByTestId("move-status-recovery-alert");
    await expect.element(moveErrorAlert).toBeVisible();
    await expect.element(moveErrorAlert).toHaveFocus();
    getMoves.mockResolvedValueOnce(moves({ moves: [] }));
    await page.getByRole("button", { name: "storage_moves_retry" }).click();

    await expect.element(page.getByText("storage_moves_empty")).toBeVisible();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(1);
    expect(getMoves).toHaveBeenCalledTimes(2);
  });

  test("keeps current progress visible when a pause command uses a stale revision", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    setMovesPaused.mockRejectedValue({ status: 409 });

    render(StoragePage);

    await page.getByRole("button", { name: "storage_moves_pause" }).click();

    await expect.element(page.getByText("storage_moves_stale_title")).toBeVisible();
    await expect.element(page.getByText("storage_move_state_pending")).toBeVisible();
    expect(setMovesPaused).toHaveBeenCalledWith({
      expected_revision: 4,
      moves_paused: true
    });
  });

  test("keeps policy visible and stops inventory retries after storage authority is revoked", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockRejectedValue({ status: 403 });

    render(StoragePage);

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_target_title" }))
      .toBeVisible();
    await expect.element(page.getByText("storage_settings_read_only_title")).toBeVisible();
    await expect.element(page.getByText("storage_overview_title")).not.toBeInTheDocument();
    await expect.element(page.getByText("storage_inventory_error_title")).not.toBeInTheDocument();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(1);
  });

  test("shows a scoped inventory error and retries only inventory", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockRejectedValueOnce(new Error("inventory unavailable"));

    render(StoragePage);

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_target_title" }))
      .toBeVisible();
    const inventoryErrorAlert = page.getByTestId("inventory-recovery-alert");
    await expect.element(inventoryErrorAlert).toBeVisible();
    await expect.element(inventoryErrorAlert).toHaveFocus();

    getInventory.mockResolvedValueOnce(inventory());
    await page.getByRole("button", { name: "retry" }).click();
    await page.getByRole("button", { name: "storage_inventory_caption" }).click();

    await expect.element(page.getByText("storage_content_state_available").first()).toBeVisible();
    await expect.element(page.getByText("storage_inventory_error_title")).not.toBeInTheDocument();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(2);
  });

  test("removes stale storage totals when a refresh fails", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockResolvedValueOnce(inventory()).mockRejectedValueOnce(new Error("unavailable"));

    render(StoragePage);

    const overview = page.getByRole("region", { name: "storage_overview_title" });
    await expect
      .element(overview.getByText("12 storage_unit_kb", { exact: true }).first())
      .toBeVisible();

    await page.getByRole("button", { name: "storage_settings_refresh_status" }).click();

    await expect.element(page.getByText("storage_inventory_error_title")).toBeVisible();
    await expect
      .element(overview.getByText("12 storage_unit_kb", { exact: true }))
      .not.toBeInTheDocument();
    expect(getInventory).toHaveBeenCalledTimes(2);
  });

  test("round-trips a byte limit through human-readable units without changing its bytes", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    const sessionFileUnit = page.getByLabelText(
      'storage_limit_unit {"limit":"storage_limit_session_file"}'
    );

    await expect.element(sessionFileInput).toHaveValue(20);
    await expect.element(sessionFileUnit).toHaveTextContent("storage_unit_mb");

    await sessionFileUnit.click();
    await page.getByRole("option", { name: "storage_unit_kb" }).click();
    await expect.element(sessionFileInput).toHaveValue(20 * 1024);

    await sessionFileUnit.click();
    await page.getByRole("option", { name: "storage_unit_mb" }).click();
    await expect.element(sessionFileInput).toHaveValue(20);
    await expect.element(page.getByText("storage_settings_no_changes")).toBeVisible();
  });

  test("falls back to bytes for a stored limit that is not divisible by a larger unit", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          session_file_limit_bytes: 1025
        }
      })
    );

    render(StoragePage);

    await expect
      .element(page.getByLabelText("storage_limit_session_file", { exact: true }))
      .toHaveValue(1025);
    await expect
      .element(page.getByLabelText('storage_limit_unit {"limit":"storage_limit_session_file"}'))
      .toHaveTextContent("storage_unit_b");
  });

  test("serializes a human-readable byte limit to an exact-byte policy payload", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy({
      capabilities: [
        {
          target: "postgres_inline",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        },
        {
          target: "object_store",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        }
      ]
    });
    getPolicy.mockResolvedValue(initial);
    let resolveReplacement!: (value: ReturnType<typeof policy>) => void;
    replacePolicy.mockImplementation(
      () => new Promise<ReturnType<typeof policy>>((resolve) => (resolveReplacement = resolve))
    );

    render(StoragePage);

    await page.getByRole("radio", { name: /storage_target_object_store/ }).click();
    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("30");
    const saveButton = page.getByRole("button", { name: "storage_settings_save" });
    focusElement(saveButton.element());
    await userEvent.keyboard("{Enter}");
    await confirmStorageTargetChange();

    await expect
      .element(
        page.getByRole("alertdialog").getByRole("button", { name: "storage_settings_saving" })
      )
      .toBeDisabled();
    expect(replacePolicy).toHaveBeenCalledWith({
      expected_revision: 4,
      new_write_storage_target: "object_store",
      session_file_limit_bytes: 30 * 1024 * 1024,
      session_image_limit_bytes: 10 * 1024 * 1024,
      knowledge_file_limit_bytes: 50 * 1024 * 1024,
      transcription_audio_limit_bytes: 100 * 1024 * 1024
    });

    resolveReplacement(
      policy({
        policy: {
          ...initial.policy,
          revision: 5,
          new_write_storage_target: "object_store",
          session_file_limit_bytes: 30 * 1024 * 1024
        },
        capabilities: initial.capabilities
      })
    );

    await expect.element(page.getByText("storage_settings_no_changes")).toBeVisible();
    await expect.element(page.getByTestId("policy-save-status")).toHaveFocus();
    await expect.element(saveButton).not.toBeInTheDocument();
  });

  test("discards an unsaved policy draft through the shared settings row", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await sessionFileInput.fill("30");
    const discardButton = page.getByRole("button", { name: "discard_changes" });
    focusElement(discardButton.element());
    await userEvent.keyboard("{Enter}");

    await expect.element(sessionFileInput).toHaveValue(20);
    await expect.element(page.getByText("storage_settings_no_changes")).toBeVisible();
    await expect.element(page.getByTestId("policy-save-status")).toHaveFocus();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .not.toBeInTheDocument();
    expect(replacePolicy).not.toHaveBeenCalled();
  });

  test("requires a reload when a generic save failure has an unknown outcome", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy({
      capabilities: [
        {
          target: "postgres_inline",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        },
        {
          target: "object_store",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        }
      ]
    });
    const committed = policy({
      policy: {
        ...initial.policy,
        revision: 5,
        new_write_storage_target: "object_store",
        session_file_limit_bytes: 40 * 1024 * 1024
      },
      capabilities: initial.capabilities
    });
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(committed);
    replacePolicy.mockRejectedValue(new Error("failed"));

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await page.getByRole("radio", { name: /storage_target_object_store/ }).click();
    await sessionFileInput.fill("31");
    await page.getByRole("button", { name: "storage_settings_save" }).click();
    await confirmStorageTargetChange();

    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .toBeVisible();
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    await expect.element(page.getByTestId("policy-recovery-alert")).toHaveFocus();
    await expect.element(sessionFileInput).toHaveValue(31);
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .toBeDisabled();

    await page.getByRole("button", { name: "storage_settings_reload_latest" }).click();

    await expect.element(sessionFileInput).toHaveValue(40);
    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .not.toBeInTheDocument();
  });

  test("switches to read-only when storage authority is revoked before save", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy({
      capabilities: [
        {
          target: "postgres_inline",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        },
        {
          target: "object_store",
          configured: true,
          selectable: true,
          readiness_code: "ready"
        }
      ]
    });
    getPolicy.mockResolvedValue(initial);
    replacePolicy.mockRejectedValue({ status: 403 });

    render(StoragePage);

    await page.getByRole("radio", { name: /storage_target_object_store/ }).click();
    await page.getByLabelText("storage_limit_session_file", { exact: true }).fill("31");
    await page.getByRole("button", { name: "storage_settings_save" }).click();
    await confirmStorageTargetChange();

    await expect.element(page.getByText("storage_settings_read_only_title")).toBeVisible();
    await expect.element(page.getByText("storage_overview_title")).not.toBeInTheDocument();
    await expect
      .element(page.getByLabelText("storage_limit_session_file", { exact: true }))
      .not.toBeInTheDocument();
    await expect
      .element(
        page
          .getByRole("region", { name: "storage_settings_target_title" })
          .getByText("storage_target_postgres_inline", { exact: true })
          .first()
      )
      .toBeVisible();
    await expect
      .element(page.getByText("20 storage_unit_mb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .not.toBeInTheDocument();
  });

  test("preserves a stale draft until the administrator explicitly reloads the latest revision", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    const latest = policy({
      policy: {
        ...initial.policy,
        revision: 5,
        session_file_limit_bytes: 40 * 1024 * 1024
      }
    });
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(latest);
    replacePolicy.mockRejectedValue(
      new EneoError(
        "Deployment policy revision is stale",
        "RESPONSE",
        409,
        9046,
        {},
        { endpoint: "PUT@/admin/object-content-policy" }
      )
    );

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await sessionFileInput.fill("31");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect.element(page.getByText("storage_settings_stale_title")).toBeVisible();
    await expect.element(sessionFileInput).toHaveValue(31);
    await page.getByRole("button", { name: "storage_settings_reload_latest" }).click();

    await expect.element(sessionFileInput).toHaveValue(40);
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("keeps the draft and reports object-store readiness when selection becomes unavailable", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    replacePolicy.mockRejectedValue(
      new EneoError(
        "Object-store target is not selectable",
        "RESPONSE",
        409,
        9047,
        {},
        { endpoint: "PUT@/admin/object-content-policy" }
      )
    );

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file", { exact: true });
    await sessionFileInput.fill("31");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect.element(page.getByText("storage_settings_target_unavailable_title")).toBeVisible();
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
    await expect.element(sessionFileInput).toHaveValue(31);
    await expect.element(page.getByRole("button", { name: "storage_settings_save" })).toBeEnabled();
  });

  test("truthfully shows a degraded selected object store while preventing it from being reselected", async () => {
    testUser.canAdministerStorage = true;
    const initial = policy();
    getPolicy.mockResolvedValue(
      policy({
        policy: {
          ...initial.policy,
          new_write_storage_target: "object_store"
        },
        capabilities: [
          {
            target: "postgres_inline",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          },
          {
            target: "object_store",
            configured: true,
            selectable: false,
            readiness_code: "store_degraded"
          }
        ]
      })
    );

    render(StoragePage);

    const objectStore = page.getByRole("radio", { name: /storage_target_object_store/ });
    await expect.element(objectStore).toBeChecked();
    await expect.element(objectStore).toBeDisabled();
    await expect
      .element(page.getByText("storage_settings_selected_target_degraded_title"))
      .toBeVisible();
    await expect.element(page.getByText("storage_settings_no_move_notice")).toBeVisible();
    await expect.element(page.getByText("storage_settings_no_fallback_notice")).toBeVisible();
    await expect.element(page.getByText("storage_readiness_store_degraded").first()).toBeVisible();
  });

  test("shows an unconfigured object-store runtime failure as an error", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(
      policy({
        capabilities: [
          {
            target: "postgres_inline",
            configured: true,
            selectable: true,
            readiness_code: "ready"
          },
          {
            target: "object_store",
            configured: false,
            selectable: false,
            readiness_code: "database_unavailable"
          }
        ]
      })
    );

    render(StoragePage);

    const overview = page.getByRole("region", { name: "storage_overview_title" });
    await expect.element(overview.getByText("storage_overview_attention")).toBeVisible();
    await expect
      .element(overview.getByText("storage_readiness_database_unavailable"))
      .toBeVisible();
    await expect
      .element(overview.getByText("storage_connection_empty_title"))
      .not.toBeInTheDocument();
  });

  test("shows all five effective limits plus bounded capability and inventory facts", async () => {
    testUser.canAdministerStorage = true;
    const currentPolicy = policy();
    getPolicy.mockResolvedValue(
      policy({
        limits: currentPolicy.limits.map((limit) =>
          limit.use_case === "session_image"
            ? {
                ...limit,
                effective_bytes: limit.configured_bytes,
                operator_ceiling_bytes: 20 * 1024 * 1024,
                constraining_source: "admin_policy"
              }
            : limit
        )
      })
    );

    render(StoragePage);
    await openEffectiveLimits();

    for (const useCase of [
      "session_file",
      "session_image",
      "session_audio",
      "knowledge_file",
      "knowledge_audio"
    ]) {
      await expect.element(page.getByText(`storage_use_case_${useCase}`)).toBeVisible();
    }
    await expect
      .element(page.getByText("storage_constraint_operator_ceiling").first())
      .toBeVisible();
    await expect.element(page.getByText("storage_constraint_admin_policy").first()).toBeVisible();
    await expect
      .element(page.getByText("storage_readiness_object_store_not_configured").first())
      .toBeVisible();
    await expect
      .element(page.getByText("storage_inventory_managed_total", { exact: true }))
      .toBeVisible();
    await page.getByRole("button", { name: "storage_inventory_caption" }).click();
    const inventorySection = page.getByRole("region", { name: "storage_overview_title" });
    await expect
      .element(inventorySection.getByText("12 storage_unit_kb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(inventorySection.getByText("4 storage_unit_kb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(inventorySection.getByText("8 storage_unit_kb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(inventorySection.getByText("32 storage_unit_mb", { exact: true }).first())
      .toBeVisible();
    const connectionSection = page.getByRole("region", { name: "storage_connection_title" });
    await expect
      .element(connectionSection.getByText("storage_connection_empty_title"))
      .toBeVisible();
    await expect.element(page.getByText("storage_content_state_available").first()).toBeVisible();
    await expect.element(page.getByText("storage_inventory_owner_file_content")).toBeVisible();
    await expect.element(page.getByText("storage_inventory_allocation_other")).toBeVisible();
    await expect
      .element(
        page
          .getByRole("table", { name: "storage_inventory_managed_caption" })
          .getByText("16 storage_unit_kb", { exact: true })
      )
      .toBeVisible();
    await expect
      .element(
        page
          .getByRole("table", { name: "storage_inventory_managed_caption" })
          .getByText("4 storage_unit_kb")
      )
      .toBeVisible();
    await expect.element(page.getByText("Jul 20, 2026")).toBeVisible();
    expect(getInventory).toHaveBeenCalledTimes(1);
  });

  test("keeps managed totals visible when PostgreSQL allocation is unavailable", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockResolvedValue({
      ...inventory(),
      postgresql_allocation: null
    });

    render(StoragePage);

    await expect
      .element(page.getByText("storage_inventory_managed_total", { exact: true }))
      .toBeVisible();
    await page.getByRole("button", { name: "storage_inventory_caption" }).click();
    await expect
      .element(page.getByText("storage_inventory_allocation_unavailable_title"))
      .toBeVisible();
  });

  test("counts deletion-pending content until deletion has completed", async () => {
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    const currentInventory = inventory();
    getInventory.mockResolvedValue({
      ...currentInventory,
      inventory: [
        ...currentInventory.inventory,
        {
          owner: "file_content",
          target: "postgres_inline",
          state: "delete_pending",
          count: 1,
          bytes: 2 * 1024,
          oldest_created_at: "2026-07-19T10:00:00Z"
        }
      ]
    });

    render(StoragePage);

    const overview = page.getByRole("region", { name: "storage_overview_title" });
    await expect
      .element(overview.getByText("14 storage_unit_kb", { exact: true }).first())
      .toBeVisible();
    await expect
      .element(overview.getByText("30 storage_unit_kb", { exact: true }))
      .not.toBeInTheDocument();
  });

  test("labels both storage locations when one share is very small", async () => {
    document.documentElement.dataset.theme = "light";
    testUser.canAdministerStorage = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockResolvedValue({
      ...inventory(),
      inventory: [
        {
          owner: "file_content",
          target: "postgres_inline",
          state: "available",
          count: 100,
          bytes: 100 * 1024 * 1024 * 1024,
          oldest_created_at: "2026-07-20T10:00:00Z"
        },
        {
          owner: "knowledge_file",
          target: "object_store",
          state: "available",
          count: 1,
          bytes: 1024 * 1024,
          oldest_created_at: "2026-07-19T10:00:00Z"
        }
      ]
    });

    render(StoragePage);

    const overview = page.getByRole("region", { name: "storage_overview_title" });
    await expect.element(overview).toBeVisible();
    const distribution = overview
      .getByRole("img", { name: /storage_overview_distribution_label/ })
      .element();
    const postgresqlSegment = distribution.querySelector("[data-storage-segment='postgresql']")!;
    const objectStoreSegment = distribution.querySelector("[data-storage-segment='object-store']")!;
    const postgresqlSwatch = overview
      .element()
      .querySelector("[data-storage-swatch='postgresql']")!;
    const objectStoreSwatch = overview
      .element()
      .querySelector("[data-storage-swatch='object-store']")!;

    expect(objectStoreSegment.getBoundingClientRect().width).toBeGreaterThanOrEqual(4);
    expect(getComputedStyle(postgresqlSwatch).backgroundColor).toBe(
      getComputedStyle(postgresqlSegment).backgroundColor
    );
    expect(getComputedStyle(objectStoreSwatch).backgroundColor).toBe(
      getComputedStyle(objectStoreSegment).backgroundColor
    );
    expect(getComputedStyle(postgresqlSwatch).backgroundColor).not.toBe(
      getComputedStyle(objectStoreSwatch).backgroundColor
    );
  });
});
