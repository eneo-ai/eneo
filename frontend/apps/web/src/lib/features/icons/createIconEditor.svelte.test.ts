import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const api = vi.hoisted(() => ({ delete: vi.fn() }));

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    icons: { delete: api.delete, upload: vi.fn(), url: ({ id }: { id: string }) => `/icons/${id}/` }
  })
}));

import { createIconEditor } from "./createIconEditor.svelte";

function editorFor(options: { staged?: boolean; setIconId?: (id: string | null) => unknown } = {}) {
  const calls: string[] = [];
  let iconId: string | null = "icon-1";
  api.delete.mockImplementation(async ({ id }: { id: string }) => {
    calls.push(`delete ${id}`);
  });
  const editor = createIconEditor({
    iconId: () => iconId,
    setIconId:
      options.setIconId ??
      (async (id) => {
        calls.push(`set ${id}`);
        iconId = id;
      }),
    staged: options.staged
  });
  return { editor, calls };
}

describe("createIconEditor remove", () => {
  beforeEach(() => {
    api.delete.mockReset();
  });

  // The server refuses to delete an icon a resource still shows.
  it("clears the icon from its resource before deleting it", async () => {
    const { editor, calls } = editorFor();

    await editor.remove();

    expect(calls).toEqual(["set null", "delete icon-1"]);
    expect(editor.url).toBeNull();
    expect(editor.error).toBeNull();
  });

  it("keeps the removal when the server keeps an icon another resource shows", async () => {
    const { editor } = editorFor();
    api.delete.mockRejectedValueOnce(new Error("The icon is in use."));

    await editor.remove();

    expect(editor.url).toBeNull();
    expect(editor.error).toBeNull();
  });

  it("leaves a staged removal's icon for the save to detach", async () => {
    const { editor, calls } = editorFor({ staged: true });

    await editor.remove();

    expect(calls).toEqual(["set null"]);
    expect(editor.url).toBeNull();
  });

  it("deletes nothing when the icon cannot be cleared", async () => {
    const { editor } = editorFor({
      setIconId: async () => {
        throw new Error("offline");
      }
    });

    await editor.remove();

    expect(api.delete).not.toHaveBeenCalled();
    expect(editor.url).toBe("/icons/icon-1/");
    expect(editor.error).toBe(m.avatar_delete_failed());
  });
});
