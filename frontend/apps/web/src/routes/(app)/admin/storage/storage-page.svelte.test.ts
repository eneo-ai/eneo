import { page } from "@vitest/browser/context";
import { EneoError } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const getPolicy = vi.hoisted(() => vi.fn());
const replacePolicy = vi.hoisted(() => vi.fn());
const testUser = vi.hoisted(() => ({ isPlatformAdmin: false }));

vi.mock("$lib/core/AppContext.js", () => ({
  getAppContext: () => ({
    user: {
      is_platform_admin: testUser.isPlatformAdmin
    }
  })
}));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    objectContentPolicy: {
      get: getPolicy,
      replace: replacePolicy
    }
  })
}));

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy<Record<string, unknown>>(
    {},
    {
      get: (_target, key) => {
        const label = String(key);
        return (params?: Record<string, unknown>) =>
          params ? `${label} ${JSON.stringify(params)}` : label;
      }
    }
  )
}));

vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "en"
}));

import StoragePage from "./+page.svelte";

function policy(overrides: Record<string, unknown> = {}) {
  return {
    policy: {
      revision: 4,
      new_write_storage_target: "postgres_inline",
      session_file_limit_bytes: 20 * 1024 * 1024,
      session_image_limit_bytes: 10 * 1024 * 1024,
      knowledge_file_limit_bytes: 50 * 1024 * 1024,
      transcription_audio_limit_bytes: 100 * 1024 * 1024,
      updated_by_actor: "platform_admin",
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
        effective_bytes: 50 * 1024 * 1024,
        storage_target: null,
        operator_ceiling_bytes: null,
        constraining_source: "admin_policy"
      },
      {
        use_case: "knowledge_audio",
        configured_bytes: 100 * 1024 * 1024,
        effective_bytes: 100 * 1024 * 1024,
        storage_target: null,
        operator_ceiling_bytes: null,
        constraining_source: "admin_policy"
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
    inventory: [
      {
        target: "postgres_inline",
        state: "available",
        count: 3,
        bytes: 4096,
        oldest_created_at: "2026-07-20T10:00:00Z"
      }
    ],
    ...overrides
  };
}

describe("admin storage settings page", () => {
  beforeEach(() => {
    testUser.isPlatformAdmin = false;
    getPolicy.mockReset();
    replacePolicy.mockReset();
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
    await expect.element(page.getByText("storage_inventory_title")).toBeVisible();
    await expect.element(page.getByText("4 KB")).toBeVisible();
  });

  test("shows a failed initial read and retries through the same policy owner", async () => {
    getPolicy.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(policy());

    render(StoragePage);

    await expect.element(page.getByText("storage_settings_load_error_title")).toBeVisible();
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
    await expect.element(page.getByLabelText("storage_limit_session_file")).toBeDisabled();
    await expect.element(page.getByLabelText("storage_limit_session_image")).toBeDisabled();
    await expect.element(page.getByLabelText("storage_limit_knowledge_file")).toBeDisabled();
    await expect.element(page.getByLabelText("storage_limit_transcription_audio")).toBeDisabled();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .not.toBeInTheDocument();
  });

  test("lets a platform administrator replace all policy values and reports pending and success", async () => {
    testUser.isPlatformAdmin = true;
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
    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect
      .element(page.getByRole("button", { name: "storage_settings_saving" }))
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

    await expect.element(page.getByText("storage_settings_save_success")).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .toBeDisabled();
  });

  test("requires a reload when a generic save failure has an unknown outcome", async () => {
    testUser.isPlatformAdmin = true;
    const initial = policy();
    const committed = policy({
      policy: {
        ...initial.policy,
        revision: 5,
        new_write_storage_target: "object_store",
        session_file_limit_bytes: 40 * 1024 * 1024
      }
    });
    getPolicy.mockResolvedValueOnce(initial).mockResolvedValueOnce(committed);
    replacePolicy.mockRejectedValue(new Error("failed"));

    render(StoragePage);

    const sessionFileInput = page.getByLabelText("storage_limit_session_file");
    await sessionFileInput.fill("32505856");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .toBeVisible();
    await expect.element(sessionFileInput).toHaveValue(32_505_856);
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .toBeDisabled();

    await page.getByRole("button", { name: "storage_settings_reload_latest" }).click();

    await expect.element(sessionFileInput).toHaveValue(40 * 1024 * 1024);
    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .not.toBeInTheDocument();
  });

  test("switches to read-only when platform-admin authority is revoked before save", async () => {
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());
    replacePolicy.mockRejectedValue({ status: 403 });

    render(StoragePage);

    await page.getByLabelText("storage_limit_session_file").fill("32505856");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect.element(page.getByText("storage_settings_read_only_title")).toBeVisible();
    await expect.element(page.getByLabelText("storage_limit_session_file")).toBeDisabled();
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText("storage_settings_save_outcome_unknown_title"))
      .not.toBeInTheDocument();
  });

  test("preserves a stale draft until the administrator explicitly reloads the latest revision", async () => {
    testUser.isPlatformAdmin = true;
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

    const sessionFileInput = page.getByLabelText("storage_limit_session_file");
    await sessionFileInput.fill("32505856");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect.element(page.getByText("storage_settings_stale_title")).toBeVisible();
    await expect.element(sessionFileInput).toHaveValue(32_505_856);
    await page.getByRole("button", { name: "storage_settings_reload_latest" }).click();

    await expect.element(sessionFileInput).toHaveValue(40 * 1024 * 1024);
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
  });

  test("keeps the draft and reports object-store readiness when selection becomes unavailable", async () => {
    testUser.isPlatformAdmin = true;
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

    const sessionFileInput = page.getByLabelText("storage_limit_session_file");
    await sessionFileInput.fill("32505856");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    await expect.element(page.getByText("storage_settings_target_unavailable_title")).toBeVisible();
    await expect.element(page.getByText("storage_settings_stale_title")).not.toBeInTheDocument();
    await expect.element(sessionFileInput).toHaveValue(32_505_856);
    await expect.element(page.getByRole("button", { name: "storage_settings_save" })).toBeEnabled();
  });

  test("truthfully shows a degraded selected object store while preventing it from being reselected", async () => {
    testUser.isPlatformAdmin = true;
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

  test("shows all five effective limits plus bounded capability and inventory facts", async () => {
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

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
    await expect.element(page.getByText("storage_content_state_available")).toBeVisible();
    await expect.element(page.getByText("4 KB")).toBeVisible();
    await expect.element(page.getByText("Jul 20, 2026")).toBeVisible();
  });
});
