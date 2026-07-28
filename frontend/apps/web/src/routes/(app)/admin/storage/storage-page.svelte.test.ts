import { page } from "@vitest/browser/context";
import { EneoError } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const getPolicy = vi.hoisted(() => vi.fn());
const getInventory = vi.hoisted(() => vi.fn());
const getMoves = vi.hoisted(() => vi.fn());
const queueMoves = vi.hoisted(() => vi.fn());
const setMovesPaused = vi.hoisted(() => vi.fn());
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
      getInventory,
      getMoves,
      queueMoves,
      setMovesPaused,
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
      moves_paused: false,
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
    ...overrides
  };
}

function inventory() {
  return {
    inventory: [
      {
        target: "postgres_inline",
        state: "available",
        count: 3,
        bytes: 4096,
        oldest_created_at: "2026-07-20T10:00:00Z"
      }
    ]
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

describe("admin storage settings page", () => {
  beforeEach(() => {
    testUser.isPlatformAdmin = false;
    getPolicy.mockReset();
    getInventory.mockReset();
    getInventory.mockResolvedValue(inventory());
    getMoves.mockReset();
    getMoves.mockResolvedValue(moves());
    queueMoves.mockReset();
    setMovesPaused.mockReset();
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
    await expect.element(page.getByText("storage_inventory_title")).not.toBeInTheDocument();
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
    expect(getInventory).not.toHaveBeenCalled();
    expect(getMoves).not.toHaveBeenCalled();
  });

  test("queues a bounded page and pauses or resumes through revision-fenced commands", async () => {
    testUser.isPlatformAdmin = true;
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
    await page.getByLabelText("storage_moves_limit").fill("7");
    await page.getByRole("button", { name: "storage_moves_queue" }).click();

    expect(queueMoves).toHaveBeenCalledWith({ target: "object_store", limit: 7 });
    await expect.element(page.getByText(/storage_moves_queue_result/)).toBeVisible();

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
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());
    queueMoves.mockResolvedValue({ queued_count: 1, target_too_large_count: 0 });

    render(StoragePage);

    await page.getByLabelText("storage_moves_target").click();
    await page.getByRole("option", { name: "storage_target_postgres_inline" }).click();
    const queueButton = page.getByRole("button", { name: "storage_moves_queue" });
    await expect.element(queueButton).toBeEnabled();
    await queueButton.click();

    expect(queueMoves).toHaveBeenCalledWith({ target: "postgres_inline", limit: 25 });
  });

  test("defaults the move destination to the current policy target", async () => {
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());

    render(StoragePage);

    await expect
      .element(page.getByLabelText("storage_moves_target"))
      .toHaveTextContent("storage_target_postgres_inline");
  });

  test("shows progress only on the move action that is running", async () => {
    testUser.isPlatformAdmin = true;
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
    await expect.element(pauseButton).toBeDisabled();
    await expect.element(queueButton).toHaveAttribute("aria-busy", "false");
    await expect.element(pauseButton).toHaveAttribute("aria-busy", "true");
    expect(queueButton.element().querySelector('[data-icon="inline-start"]')).toBeNull();
    expect(pauseButton.element().querySelector('[data-icon="inline-start"]')).not.toBeNull();

    resolvePause({ policy_revision: 5, paused: true });
    await clickPause;
    await expect.element(page.getByRole("button", { name: "storage_moves_resume" })).toBeEnabled();
  });

  test("locks policy inputs while pause recovery is pending", async () => {
    testUser.isPlatformAdmin = true;
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
      page.getByLabelText("storage_limit_session_file"),
      page.getByLabelText("storage_limit_session_image"),
      page.getByLabelText("storage_limit_knowledge_file"),
      page.getByLabelText("storage_limit_transcription_audio")
    ];
    await expect.element(target).toBeEnabled();
    const pause = (async () => {
      await page.getByRole("button", { name: "storage_moves_pause" }).click();
    })();

    await expect.element(target).toBeDisabled();
    for (const limit of limits) await expect.element(limit).toBeDisabled();
    await expect.element(limits[0]).toHaveValue(20 * 1024 * 1024);

    rejectPause(new Error("response lost"));
    await pause;
    await expect.element(page.getByText("storage_moves_outcome_unknown_title")).toBeVisible();
    await expect.element(target).toBeEnabled();
    for (const limit of limits) await expect.element(limit).toBeEnabled();
    await expect.element(limits[1]).toHaveValue(12 * 1024 * 1024);
  });

  test("keeps the selected destination and limit when readiness rejects queueing", async () => {
    testUser.isPlatformAdmin = true;
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
    const limit = page.getByLabelText("storage_moves_limit");
    await limit.fill("7");
    await page.getByRole("button", { name: "storage_moves_queue" }).click();

    await expect.element(page.getByText("storage_moves_action_error_title")).toBeVisible();
    await expect.element(target).toHaveTextContent("storage_target_object_store");
    await expect.element(limit).toHaveValue(7);
  });

  test("reloads committed queue progress when the command outcome is unknown", async () => {
    testUser.isPlatformAdmin = true;
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
    const clickQueue = (async () => {
      await queueButton.click();
    })();

    await expect.element(page.getByText("storage_moves_loading")).toBeVisible();
    await expect.element(queueButton).toBeDisabled();
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
    await expect.element(page.getByText("4", { exact: true })).toBeVisible();
  });

  test("keeps a dirty draft on its old baseline after a committed pause response is lost", async () => {
    testUser.isPlatformAdmin = true;
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

    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    await page.getByRole("button", { name: "storage_moves_pause" }).click();
    await expect.element(page.getByText("storage_moves_outcome_unknown_title")).toBeVisible();
    await expect.element(page.getByText("storage_settings_stale_title")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "storage_moves_resume" })).toBeEnabled();
    await expect.element(page.getByLabelText("storage_limit_session_file")).toHaveValue(31457280);
    await expect.element(page.getByLabelText("storage_limit_session_image")).toHaveValue(10485760);
    await expect
      .element(page.getByRole("button", { name: "storage_settings_save" }))
      .toBeDisabled();
    expect(replacePolicy).not.toHaveBeenCalled();
  });

  test("keeps the full policy revision as the replacement baseline", async () => {
    testUser.isPlatformAdmin = true;
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

    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    expect(replacePolicy).toHaveBeenCalledWith(expect.objectContaining({ expected_revision: 4 }));
  });

  test("refreshes the full policy after pausing from a newer move projection", async () => {
    testUser.isPlatformAdmin = true;
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
    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    await page.getByRole("button", { name: "storage_settings_save" }).click();

    expect(replacePolicy).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_revision: 6,
        session_image_limit_bytes: 12 * 1024 * 1024
      })
    );
  });

  test("serializes policy saves and pause commands on their shared revision", async () => {
    testUser.isPlatformAdmin = true;
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

    await page.getByLabelText("storage_limit_session_file").fill("31457280");
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

    await page.getByLabelText("storage_limit_session_image").fill("11534336");
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
    testUser.isPlatformAdmin = true;
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

    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    await page.getByRole("button", { name: "storage_settings_save" }).click();
    await page.getByRole("button", { name: "storage_moves_resume" }).click();

    expect(setMovesPaused).toHaveBeenCalledWith({
      expected_revision: 5,
      moves_paused: false
    });
  });

  test("keeps a newer move projection when an older full policy response finishes later", async () => {
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

    await page.getByLabelText("storage_limit_session_file").fill("31457280");
    const save = (async () => {
      await page.getByRole("button", { name: "storage_settings_save" }).click();
    })();
    await expect.element(page.getByRole("button", { name: "storage_moves_pause" })).toBeDisabled();
    await page.getByRole("button", { name: "storage_moves_queue" }).click();
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
    testUser.isPlatformAdmin = true;
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
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());
    getMoves.mockRejectedValueOnce(new Error("progress unavailable"));

    render(StoragePage);

    await expect.element(page.getByText("storage_moves_load_error_title")).toBeVisible();
    getMoves.mockResolvedValueOnce(moves({ moves: [] }));
    await page.getByRole("button", { name: "storage_moves_retry" }).click();

    await expect.element(page.getByText("storage_moves_empty")).toBeVisible();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(1);
    expect(getMoves).toHaveBeenCalledTimes(2);
  });

  test("keeps current progress visible when a pause command uses a stale revision", async () => {
    testUser.isPlatformAdmin = true;
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

  test("keeps policy visible and stops inventory retries after platform authority is revoked", async () => {
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockRejectedValue({ status: 403 });

    render(StoragePage);

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_target_title" }))
      .toBeVisible();
    await expect.element(page.getByText("storage_settings_read_only_title")).toBeVisible();
    await expect.element(page.getByText("storage_inventory_title")).not.toBeInTheDocument();
    await expect.element(page.getByText("storage_inventory_error_title")).not.toBeInTheDocument();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(1);
  });

  test("shows a scoped inventory error and retries only inventory", async () => {
    testUser.isPlatformAdmin = true;
    getPolicy.mockResolvedValue(policy());
    getInventory.mockRejectedValueOnce(new Error("inventory unavailable"));

    render(StoragePage);

    await expect
      .element(page.getByRole("heading", { name: "storage_settings_target_title" }))
      .toBeVisible();
    await expect.element(page.getByText("storage_inventory_error_title")).toBeVisible();

    getInventory.mockResolvedValueOnce(inventory());
    await page.getByRole("button", { name: "retry" }).click();

    await expect.element(page.getByText("storage_content_state_available")).toBeVisible();
    await expect.element(page.getByText("storage_inventory_error_title")).not.toBeInTheDocument();
    expect(getPolicy).toHaveBeenCalledTimes(1);
    expect(getInventory).toHaveBeenCalledTimes(2);
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
    await expect.element(page.getByText("storage_inventory_title")).not.toBeInTheDocument();
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
    testUser.isPlatformAdmin = true;
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
    await expect
      .element(page.getByRole("table", { name: "storage_inventory_caption" }).getByText("4 KB"))
      .toBeVisible();
    await expect.element(page.getByText("Jul 20, 2026")).toBeVisible();
    expect(getInventory).toHaveBeenCalledTimes(1);
  });
});
