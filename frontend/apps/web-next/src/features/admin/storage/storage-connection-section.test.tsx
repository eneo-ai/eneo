// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: { GET: get, POST: post, PUT: put, DELETE: remove }
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { StorageConnectionSection } from "./storage-connection-section";

type Connection = Schema<"ObjectStoreConnectionPublic">;
const current: Connection = {
  source: "admin",
  configured: true,
  credentials_can_be_managed: true,
  revision: 9,
  endpoint_url: "https://current.example",
  bucket: "current",
  region: "se-1",
  addressing_style: "path",
  previous_destination: {
    revision: 5,
    endpoint_url: "https://old.example",
    bucket: "old",
    region: "se-1",
    addressing_style: "path",
    updated_at: "2026-09-25T00:00:00Z"
  }
};
const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const failed = (status: number, code: string) =>
  Promise.resolve({
    error: { message: "Operation failed", eneo_error_code: 9038, code },
    response: new Response("{}", { status })
  });
const onConnectionChanged = vi.fn().mockResolvedValue(undefined);
const onAuthorityRevoked = vi.fn();

function show(canEdit = true) {
  render(
    <StorageConnectionSection
      capability={{
        target: "object_store",
        configured: true,
        selectable: true,
        readiness_code: "ready"
      }}
      canEdit={canEdit}
      onConnectionChanged={onConnectionChanged}
      onAuthorityRevoked={onAuthorityRevoked}
    />
  );
}

beforeEach(() => {
  get.mockImplementation(() => ok(current));
  post.mockImplementation(() => ok(current));
  put.mockImplementation(() => ok(current));
  remove.mockImplementation(() => ok(undefined));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("object-store connection lifecycle", () => {
  it("keeps protected connection details and actions hidden from read-only viewers", () => {
    show(false);
    expect(screen.getByText("storage_connection_storage_admin_only")).toBeTruthy();
    expect(screen.queryByText("https://current.example")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it("tests and creates a new destination without changing the storage target", async () => {
    get.mockImplementation(() =>
      ok({ source: "unconfigured", configured: false, credentials_can_be_managed: true })
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "storage_connection_add_action" }));
    fireEvent.change(screen.getByLabelText("storage_connection_endpoint"), {
      target: { value: "https://new.example" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_bucket"), {
      target: { value: "new" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_region"), {
      target: { value: "se-1" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_access_key"), {
      target: { value: "key-id" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_secret_key"), {
      target: { value: "secret" }
    });
    fireEvent.click(screen.getByRole("button", { name: "storage_connection_test_and_save" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/admin/object-store-connection", {
        body: {
          endpoint_url: "https://new.example",
          bucket: "new",
          region: "se-1",
          access_key_id: "key-id",
          secret_access_key: "secret",
          addressing_style: "path"
        }
      })
    );
    expect(await screen.findByText("storage_connection_created_title")).toBeTruthy();
  });

  it("shows each missing field at the field on submit, and moves focus to the first", async () => {
    get.mockImplementation(() =>
      ok({ source: "unconfigured", configured: false, credentials_can_be_managed: true })
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "storage_connection_add_action" }));
    const save = screen.getByRole("button", { name: "storage_connection_test_and_save" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((save as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(save);
    const endpoint = screen.getByLabelText("storage_connection_endpoint");
    const [problem, help] = endpoint.getAttribute("aria-describedby")!.split(" ");
    expect(document.getElementById(problem!)?.textContent).toBe("required_field");
    expect(document.getElementById(help!)?.textContent).toBe("storage_connection_endpoint_help");
    for (const label of [
      "storage_connection_bucket",
      "storage_connection_region",
      "storage_connection_access_key",
      "storage_connection_secret_key"
    ]) {
      expect(screen.getByLabelText(label).getAttribute("aria-invalid")).toBe("true");
    }
    expect(document.activeElement).toBe(endpoint);

    fireEvent.change(endpoint, { target: { value: "https://new.example" } });
    fireEvent.change(screen.getByLabelText("storage_connection_bucket"), {
      target: { value: "new" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_region"), {
      target: { value: "se-1" }
    });
    fireEvent.click(save);
    expect(endpoint.getAttribute("aria-invalid")).toBeNull();
    expect(document.activeElement).toBe(screen.getByLabelText("storage_connection_access_key"));
    expect(post).not.toHaveBeenCalled();
  });

  it("submits a destination change to the dedicated switch endpoint", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "storage_switch_action" }));
    fireEvent.change(screen.getByLabelText("storage_connection_endpoint"), {
      target: { value: "https://another.example" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_bucket"), {
      target: { value: "another" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_region"), {
      target: { value: "se-1" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_access_key"), {
      target: { value: "key-id" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_secret_key"), {
      target: { value: "secret" }
    });
    fireEvent.click(screen.getByRole("button", { name: "storage_switch_test_and_switch" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/admin/object-store-connection/destination", {
        body: {
          endpoint_url: "https://another.example",
          bucket: "another",
          region: "se-1",
          access_key_id: "key-id",
          secret_access_key: "secret",
          addressing_style: "path"
        }
      })
    );
    expect(await screen.findByText("storage_switch_done_title")).toBeTruthy();
  });

  it("rotates both keys against the revision of the connection shown to the administrator", async () => {
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "storage_connection_rotate_action" })
    );
    fireEvent.change(screen.getByLabelText("storage_connection_access_key"), {
      target: { value: "key-id" }
    });
    fireEvent.change(screen.getByLabelText("storage_connection_secret_key"), {
      target: { value: "secret" }
    });
    fireEvent.click(screen.getByRole("button", { name: "storage_connection_test_and_rotate" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/admin/object-store-connection/credentials", {
        body: { expected_revision: 9, access_key_id: "key-id", secret_access_key: "secret" }
      })
    );
    expect(await screen.findByText("storage_connection_rotated_title")).toBeTruthy();
    expect(onConnectionChanged).toHaveBeenCalledTimes(1);
  });

  it("reads state before allowing another switch-back after an uncertain response", async () => {
    post.mockImplementation(() => failed(503, "object_store_connection_mutation_outcome_unknown"));
    get
      .mockImplementationOnce(() => ok(current))
      .mockImplementationOnce(() =>
        ok({
          ...current,
          endpoint_url: "https://old.example",
          bucket: "old",
          revision: 10
        })
      );
    show();
    fireEvent.click(await screen.findByRole("button", { name: /storage_switch_previous_title/ }));
    fireEvent.click(screen.getByRole("button", { name: "storage_switch_back_action" }));
    expect(await screen.findByText("storage_switch_back_done_title")).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1);
    expect(onConnectionChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps focus on a busy switch-back and switches back once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    show();
    fireEvent.click(await screen.findByRole("button", { name: /storage_switch_previous_title/ }));
    const switchBack = screen.getByRole("button", { name: "storage_switch_back_action" });
    switchBack.focus();

    fireEvent.click(switchBack);

    await waitFor(() => expect(switchBack.getAttribute("aria-busy")).toBe("true"));
    expect(switchBack.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(switchBack);
    fireEvent.click(switchBack);
    fireEvent.click(screen.getByRole("button", { name: "storage_switch_forget_action" }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(remove).not.toHaveBeenCalled();
  });

  it("forgets only the archived revision selected by the administrator", async () => {
    get
      .mockImplementationOnce(() => ok(current))
      .mockImplementationOnce(() => ok({ ...current, previous_destination: null }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: /storage_switch_previous_title/ }));
    fireEvent.click(screen.getByRole("button", { name: "storage_switch_forget_action" }));
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith("/api/v1/admin/object-store-connection/previous", {
        params: { query: { expected_revision: 5 } }
      })
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /storage_switch_previous_title/ })).toBeNull()
    );
  });

  it("retains an unresolved abandon until a later read confirms the result", async () => {
    const pending = {
      revision: 3,
      endpoint_url: "https://pending.example",
      bucket: "pending",
      region: "se-1",
      addressing_style: "path" as const,
      updated_at: "2026-09-25T00:00:00Z"
    };
    get
      .mockImplementationOnce(() => ok({ ...current, pending_destination: pending }))
      .mockImplementationOnce(() => failed(503, "object_store_connection_database_unavailable"))
      .mockImplementationOnce(() => ok({ ...current, pending_destination: null }));
    remove.mockImplementation(() =>
      failed(503, "object_store_connection_mutation_outcome_unknown")
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "storage_pending_abandon_action" }));
    expect(await screen.findByText("storage_connection_load_error_title")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    await waitFor(() => expect(screen.queryByText("storage_pending_title")).toBeNull());
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
