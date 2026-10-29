// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "@/lib/api/base";
import { renderInApp } from "@/test/render";
import { IconField, iconUrl } from "./icon-field";

const api = vi.hoisted(() => ({ DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/toast", () => ({ toast: { error: toastError } }));
// The selected transport may inspect an error without consuming the body.
const transportFetch = vi.hoisted(() =>
  vi.fn<typeof fetch>(async (input, init) => {
    const response = await fetch(input, init);
    if (!response.ok) await response.clone().text();
    return response;
  })
);
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  apiFetch: transportFetch
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  api.DELETE.mockReset();
  toastError.mockReset();
  transportFetch.mockClear();
});

function upload(
  onSave: (iconId: string | null) => Promise<unknown>,
  response = () => new Response(JSON.stringify({ id: "icon-new" }), { status: 200 })
) {
  const fetchMock = vi.fn(async () => response());
  vi.stubGlobal("fetch", fetchMock);
  api.DELETE.mockResolvedValue({});
  const { container } = renderInApp(<IconField iconId="icon-old" onSave={onSave} />);
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, {
    target: { files: [new File(["x"], "icon.png", { type: "image/png" })] }
  });
  return fetchMock;
}

it("serves icons under the API base", () => {
  expect(iconUrl("icon-1")).toBe(`${API_BASE}/api/v1/icons/icon-1/`);
  expect(iconUrl(null)).toBeNull();
});

describe("IconField", () => {
  // The server releases the icon a saved change replaced.
  it("sends no delete when the new icon is saved", async () => {
    const onSave = vi.fn(async () => {});

    upload(onSave);

    await waitFor(() => expect(onSave).toHaveBeenCalledWith("icon-new"));
    expect(api.DELETE).not.toHaveBeenCalled();
  });

  it("deletes the upload when the resource refuses it", async () => {
    upload(async () => {
      throw new Error("refused");
    });

    await waitFor(() =>
      expect(api.DELETE).toHaveBeenCalledWith("/api/v1/icons/{id}/", {
        params: { path: { id: "icon-new" } }
      })
    );
  });

  it("only saves the removal", async () => {
    const onSave = vi.fn(async () => {});
    renderInApp(<IconField iconId="icon-old" onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: /delete|ta bort/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(null));
    expect(api.DELETE).not.toHaveBeenCalled();
  });

  it.each([
    [401, 9001],
    [403, 9070]
  ])(
    "reports a refused %i upload through the shared transport once, then shows its own error",
    async (status, code) => {
      const onSave = vi.fn(async () => {});
      const refused = Response.json({ message: "Refused", eneo_error_code: code }, { status });

      const fetchMock = upload(onSave, () => refused);

      await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
      expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/v1/icons/`, expect.anything());
      expect(transportFetch).toHaveBeenCalledTimes(1);
      expect(transportFetch).toHaveBeenCalledWith(`${API_BASE}/api/v1/icons/`, expect.anything());
      expect(onSave).not.toHaveBeenCalled();
      // The owner read its copy; the upload's own response is still unread.
      await expect(refused.json()).resolves.toMatchObject({ message: "Refused" });
    }
  );
});
