// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { IconField } from "./icon-field";

const api = vi.hoisted(() => ({ DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  api.DELETE.mockReset();
});

function upload(onSave: (iconId: string | null) => Promise<unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ id: "icon-new" }), { status: 200 }))
  );
  api.DELETE.mockResolvedValue({});
  const { container } = renderInApp(<IconField iconId="icon-old" onSave={onSave} />);
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, {
    target: { files: [new File(["x"], "icon.png", { type: "image/png" })] }
  });
}

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
});
