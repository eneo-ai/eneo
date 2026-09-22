import type { Assistant, Eneo } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import AssistantMaterialTestHost from "./AssistantMaterialTestHost.svelte";

function setup(options: { referenceAvailable?: boolean; fileReferencesEnabled?: boolean } = {}) {
  const assistant = {
    id: "assistant",
    name: "Material test",
    prompt: { text: "", description: "" },
    inline_file_text: true,
    knowledge_mode: "inject",
    allowed_attachments: {
      accepted_file_types: [{ mimetype: "text/plain", size_limit: 1000000, extensions: [".txt"] }],
      limit: { max_files: 10, max_size: 1000000 }
    },
    attachments: [
      {
        id: "file",
        name: "test_data_5k.csv",
        mimetype: "text/csv",
        size: 562,
        inline_text: true,
        has_download_reference: options.referenceAvailable ?? true
      }
    ]
  } as unknown as Assistant;
  const uploadedFile = {
    id: "new-file",
    name: "background.txt",
    mimetype: "text/plain",
    size: 10,
    has_download_reference: true
  };
  const update = vi.fn().mockImplementation(async ({ update: changes }) => ({
    ...assistant,
    ...changes,
    attachments: changes.attachments
      ? changes.attachments.map((attachment: { id: string; inline_text: boolean }) => ({
          ...[...assistant.attachments, uploadedFile].find((file) => file.id === attachment.id),
          ...attachment
        }))
      : assistant.attachments
  }));
  const deleteFile = vi.fn();
  const eneo = {
    assistants: { update },
    files: {
      delete: deleteFile,
      upload: vi.fn().mockResolvedValue(uploadedFile)
    },
    conversations: {
      preflight: vi.fn().mockResolvedValue({
        file_tokens: 0,
        prompt_tokens: 0,
        context_reserve_tokens: 100
      })
    }
  } as unknown as Eneo;
  const screen = render(AssistantMaterialTestHost, {
    assistant,
    eneo,
    fileReferencesEnabled: options.fileReferencesEnabled ?? true
  });
  const state = () => JSON.parse(screen.container.querySelector("output")!.textContent!);
  return { screen, state, update, deleteFile };
}

describe("Assistant material editor", () => {
  it("defaults new uploads to on-demand, preserves existing files, and saves an explicit inline choice", async () => {
    const { screen, state, update } = setup();
    const input = screen.container.querySelector("input[type=file]") as HTMLInputElement;
    const files = new DataTransfer();
    files.items.add(new File(["Background"], "background.txt", { type: "text/plain" }));
    input.files = files.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(state().attachments).toHaveLength(2));
    expect(state().attachments).toMatchObject([
      { id: "file", inline_text: true },
      { id: "new-file", inline_text: false }
    ]);
    await page.getByRole("button", { name: m.save_changes(), exact: true }).click();
    await vi.waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        assistant: expect.objectContaining({ id: "assistant" }),
        update: {
          attachments: expect.arrayContaining([
            expect.objectContaining({ id: "file", inline_text: true }),
            expect.objectContaining({ id: "new-file", inline_text: false })
          ])
        }
      })
    );
    await page
      .getByRole("button", { name: m.material_change_file({ name: "background.txt" }) })
      .click();
    await expect
      .element(
        page
          .getByRole("radiogroup", { name: m.material_change_file({ name: "background.txt" }) })
          .getByRole("radio", { name: m.material_open_when_needed(), exact: true })
      )
      .toBeChecked();
    expect(state().dirty).toBe(false);
    await page.getByRole("radio", { name: m.material_file_always_option(), exact: true }).click();
    expect(state().attachments[1].inline_text).toBe(true);
    await page.getByRole("button", { name: m.save_changes(), exact: true }).click();
    await vi.waitFor(() =>
      expect(update).toHaveBeenLastCalledWith({
        assistant: expect.objectContaining({ id: "assistant" }),
        update: {
          attachments: expect.arrayContaining([
            expect.objectContaining({ id: "new-file", inline_text: true })
          ])
        }
      })
    );
  });

  it("keeps both file modes and the uploader under attachments, and restores the mode on discard", async () => {
    const { screen, state, update, deleteFile } = setup();
    expect(state().dirty).toBe(false);
    await expect
      .element(page.getByRole("heading", { name: m.attachments(), exact: true }))
      .toBeVisible();
    await page
      .getByRole("button", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
      .click();
    await page
      .getByRole("radiogroup", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
      .getByRole("radio", { name: m.material_open_when_needed(), exact: true })
      .click();
    await expect
      .element(page.getByText(m.material_file_lookup_status(), { exact: true }))
      .toBeVisible();
    const attachmentSection = screen.container.querySelector(
      'section[aria-labelledby="material-attachments-heading"]'
    )!;
    expect(attachmentSection.textContent).toContain("test_data_5k.csv");
    expect(attachmentSection.querySelector("input[type=file]")).not.toBeNull();
    expect(state()).toMatchObject({
      attachments: [{ id: "file", inline_text: false }],
      inline_file_text: true,
      knowledge_mode: "inject",
      dirty: true
    });
    await page.getByRole("button", { name: m.discard_all_changes(), exact: true }).click();
    await expect
      .element(page.getByText(m.material_file_inline_status(), { exact: true }))
      .toBeVisible();
    expect(state().dirty).toBe(false);
    expect(update).not.toHaveBeenCalled();
    expect(deleteFile).not.toHaveBeenCalled();
  });

  it("shows both material settings directly and saves their choices independently", async () => {
    const { state, update } = setup();
    await expect
      .element(page.getByRole("radio", { name: m.material_read_directly(), exact: true }))
      .toBeChecked();
    await expect
      .element(page.getByRole("radio", { name: m.material_before_each_answer(), exact: true }))
      .toBeChecked();
    await page.getByRole("radio", { name: m.material_open_when_needed(), exact: true }).click();
    await page.getByRole("radio", { name: m.material_when_needed(), exact: true }).click();
    await expect
      .element(page.getByRole("radio", { name: m.material_open_when_needed(), exact: true }))
      .toBeChecked();
    expect(state().attachments[0].inline_text).toBe(true);
    await page.getByRole("button", { name: m.save_changes(), exact: true }).click();
    await vi.waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        assistant: expect.objectContaining({ id: "assistant" }),
        update: { inline_file_text: false, knowledge_mode: "tool" }
      })
    );
    expect(state().dirty).toBe(false);
  });

  it("shows effective model fallback while retaining the on-demand file preference", async () => {
    const { state } = setup();
    await page
      .getByRole("button", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
      .click();
    await page
      .getByRole("radiogroup", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
      .getByRole("radio", { name: m.material_open_when_needed(), exact: true })
      .click();
    await page.getByRole("button", { name: m.completion_model() }).click();
    await expect
      .element(page.getByText(m.material_file_model_fallback(), { exact: true }).first())
      .toBeVisible();
    await expect
      .element(page.getByText(m.material_file_inline_status(), { exact: true }))
      .toBeVisible();
    expect(state().attachments[0].inline_text).toBe(false);
    await page.getByRole("button", { name: m.completion_model() }).click();
    await expect
      .element(page.getByText(m.material_file_lookup_status(), { exact: true }))
      .toBeVisible();
  });

  it.each([
    {
      referenceAvailable: false,
      fileReferencesEnabled: true,
      reason: m.attachment_mode_lookup_unavailable
    },
    {
      referenceAvailable: true,
      fileReferencesEnabled: false,
      reason: m.material_file_references_unavailable
    }
  ])(
    "explains unavailable file references without changing saved settings: %j",
    async (options) => {
      const { state } = setup(options);
      await page
        .getByRole("button", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
        .click();
      await expect
        .element(
          page
            .getByRole("radiogroup", { name: m.material_change_file({ name: "test_data_5k.csv" }) })
            .getByRole("radio", { name: m.material_open_when_needed(), exact: true })
        )
        .toBeDisabled();
      await expect.element(page.getByText(options.reason(), { exact: true })).toBeVisible();
      expect(state().dirty).toBe(false);
    }
  );
});
