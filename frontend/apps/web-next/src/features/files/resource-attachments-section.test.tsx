// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { ResourceAttachmentsSection } from "./resource-attachments-section";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  api.POST.mockReset();
  api.DELETE.mockReset();
});

const first = {
  id: "first",
  name: "First.txt",
  mimetype: "text/plain",
  size: 10,
  inline_text: false
};
const second = {
  id: "second",
  name: "Second.txt",
  mimetype: "text/plain",
  size: 10,
  inline_text: true
};
const restrictions = { accepted_file_types: [], limit: { max_files: 10, max_size: 1000 } };
const attachmentMode = {
  fileReferencesEnabled: true,
  selectedModel: { id: "model", supports_tool_calling: true }
};

it("changes an attachment reading mode through the existing save and rolls back a failed save for retry", async () => {
  const save = vi.fn().mockRejectedValueOnce(new Error("save failed")).mockResolvedValue({});
  renderInApp(
    <ResourceAttachmentsSection
      attachments={[first]}
      allowedAttachments={restrictions}
      description="Files"
      attachmentMode={attachmentMode}
      onSave={save}
    />
  );
  expect(screen.getByText("Öppnas vid behov")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Ändra hur First.txt används" }));
  const inline = screen.getByRole("radio", { name: "Läs in inför varje svar" });
  fireEvent.click(inline);
  await waitFor(() =>
    expect(
      (screen.getByRole("radio", { name: "Öppna vid behov" }) as HTMLInputElement).checked
    ).toBe(true)
  );
  fireEvent.click(inline);
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save).toHaveBeenLastCalledWith([{ id: "first", inline_text: true }]);
  expect(screen.getByText("Läses in inför varje svar")).toBeTruthy();
});

it.each([true, false])(
  "new uploads use the owning resource's reading default (assistant=%s)",
  async (assistant) => {
    const save = vi.fn().mockResolvedValue({});
    api.POST.mockResolvedValue({
      data: {
        id: "uploaded",
        name: "new.txt",
        mimetype: "text/plain",
        size: 4,
        has_download_reference: true
      },
      response: new Response("{}")
    });
    const { container } = renderInApp(
      <ResourceAttachmentsSection
        attachments={[]}
        allowedAttachments={{
          accepted_file_types: [{ mimetype: "text/plain", size_limit: 1000, extensions: [".txt"] }],
          limit: restrictions.limit
        }}
        description="Files"
        attachmentMode={
          assistant
            ? {
                fileReferencesEnabled: true,
                selectedModel: { id: "model", supports_tool_calling: true }
              }
            : undefined
        }
        onSave={save}
      />
    );
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [new File(["test"], "new.txt", { type: "text/plain" })] }
    });
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith([
        assistant ? { id: "uploaded", inline_text: false } : { id: "uploaded" }
      ])
    );
  }
);

it("formats compact token counts in the UI language", () => {
  renderInApp(
    <ResourceAttachmentsSection
      attachments={[{ ...first, token_count: 1200 }]}
      allowedAttachments={restrictions}
      description="Files"
      onSave={vi.fn()}
    />
  );
  expect(screen.getByText(/1,2\s+tn/)).toBeTruthy();
});

it("preserves an existing on-demand read mode when another attachment is removed", async () => {
  const save = vi.fn().mockResolvedValue({});
  renderInApp(
    <ResourceAttachmentsSection
      attachments={[first, second]}
      allowedAttachments={restrictions}
      description="Files"
      onSave={save}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Ta bort Second.txt" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith([{ id: "first", inline_text: false }]));
});

it("adopts a read mode changed in the other frontend before the next save", async () => {
  const save = vi.fn().mockResolvedValue({});
  const props = { allowedAttachments: restrictions, description: "Files", onSave: save };
  const view = renderInApp(
    <ResourceAttachmentsSection
      {...props}
      attachments={[{ ...first, inline_text: true }, second]}
    />
  );
  view.rerender(<ResourceAttachmentsSection {...props} attachments={[first, second]} />);
  fireEvent.click(screen.getByRole("button", { name: "Ta bort Second.txt" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith([{ id: "first", inline_text: false }]));
});

it.each([
  [
    "image",
    { ...first, mimetype: "image/png" },
    attachmentMode,
    /Den här filtypen läses in direkt/
  ],
  [
    "original",
    { ...first, has_download_reference: false },
    attachmentMode,
    /saknar ett lagrat original/
  ],
  [
    "deployment",
    first,
    { ...attachmentMode, fileReferencesEnabled: false },
    /Filåtkomst vid behov är inte tillgänglig/
  ],
  ["model", first, { ...attachmentMode, selectedModel: null }, /Välj en modell med verktygsstöd/],
  [
    "tools",
    first,
    { ...attachmentMode, selectedModel: { id: "model", supports_tool_calling: false } },
    /Den valda modellen saknar verktygsstöd/
  ]
] as const)(
  "explains the effective inline fallback and unavailable on-demand mode: %s",
  async (_name, file, mode, reason) => {
    const { container } = renderInApp(
      <ResourceAttachmentsSection
        attachments={[{ ...file, inline_text: true }]}
        allowedAttachments={restrictions}
        description="Files"
        attachmentMode={mode}
        onSave={vi.fn()}
      />
    );
    expect(screen.getByText("Läses in inför varje svar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ändra hur First.txt används" }));
    expect(screen.getByText(reason)).toBeTruthy();
    expect(
      (screen.getByRole("radio", { name: "Öppna vid behov" }) as HTMLInputElement).disabled
    ).toBe(true);
    if (_name === "tools") await expectNoAxeViolations(container);
  }
);

it("keeps the confirmed mode after rapid opposite changes and deferred save failures", async () => {
  let rejectFirst!: (error: Error) => void;
  let rejectSecond!: (error: Error) => void;
  const save = vi
    .fn()
    .mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectFirst = reject;
      })
    )
    .mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectSecond = reject;
      })
    )
    .mockResolvedValue({});
  renderInApp(
    <ResourceAttachmentsSection
      attachments={[first]}
      allowedAttachments={restrictions}
      description="Files"
      attachmentMode={attachmentMode}
      onSave={save}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Ändra hur First.txt används" }));
  fireEvent.click(screen.getByRole("radio", { name: "Läs in inför varje svar" }));
  fireEvent.click(screen.getByRole("radio", { name: "Öppna vid behov" }));
  await act(async () => rejectFirst(new Error("first failed")));
  if (save.mock.calls.length > 1) await act(async () => rejectSecond(new Error("second failed")));
  await waitFor(() =>
    expect(
      (screen.getByRole("radio", { name: "Öppna vid behov" }) as HTMLInputElement).checked
    ).toBe(true)
  );
  expect(save).toHaveBeenCalledTimes(1);
});

it("blocks add, remove and drop during a mode save, then retries from the confirmed files", async () => {
  let fail!: (error: Error) => void;
  const save = vi
    .fn()
    .mockReturnValueOnce(
      new Promise((_, reject) => {
        fail = reject;
      })
    )
    .mockResolvedValue({});
  api.POST.mockResolvedValue({
    data: { id: "new", name: "new.txt", mimetype: "text/plain", size: 4 },
    response: new Response("{}")
  });
  const { container } = renderInApp(
    <ResourceAttachmentsSection
      attachments={[first]}
      allowedAttachments={{
        ...restrictions,
        accepted_file_types: [{ mimetype: "text/plain", extensions: [".txt"], size_limit: 1000 }]
      }}
      description="Files"
      attachmentMode={attachmentMode}
      onSave={save}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Ändra hur First.txt används" }));
  fireEvent.click(screen.getByRole("radio", { name: "Läs in inför varje svar" }));
  fireEvent.click(screen.getByRole("button", { name: "Ta bort First.txt" }));
  const input = container.querySelector('input[type="file"]')!;
  const file = new File(["test"], "new.txt", { type: "text/plain" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.drop(screen.getByText("Släpp filer här").parentElement!, {
    dataTransfer: { types: ["Files"], files: [file], items: [] }
  });
  expect(save).toHaveBeenCalledTimes(1);
  expect(api.POST).not.toHaveBeenCalled();
  expect(screen.getByText("First.txt")).toBeTruthy();
  await act(async () => fail(new Error("save failed")));
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save).toHaveBeenLastCalledWith([
    { id: "first", inline_text: false },
    { id: "new", inline_text: false }
  ]);
});

it("keeps existing files unchanged while a native upload is pending", async () => {
  let finish!: (value: unknown) => void;
  api.POST.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  const save = vi.fn().mockResolvedValue({});
  const { container } = renderInApp(
    <ResourceAttachmentsSection
      attachments={[first]}
      allowedAttachments={{
        ...restrictions,
        accepted_file_types: [{ mimetype: "text/plain", extensions: [".txt"], size_limit: 1000 }]
      }}
      description="Files"
      attachmentMode={attachmentMode}
      onSave={save}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Ändra hur First.txt används" }));
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [new File(["test"], "new.txt", { type: "text/plain" })] }
  });
  fireEvent.click(screen.getByRole("radio", { name: "Läs in inför varje svar" }));
  fireEvent.click(screen.getByRole("button", { name: "Ta bort First.txt" }));
  expect(save).not.toHaveBeenCalled();
  expect((screen.getByRole("radio", { name: "Öppna vid behov" }) as HTMLInputElement).checked).toBe(
    true
  );
  await act(async () =>
    finish({
      data: { id: "new", name: "new.txt", mimetype: "text/plain", size: 4 },
      response: new Response("{}")
    })
  );
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith([
      { id: "first", inline_text: false },
      { id: "new", inline_text: false }
    ])
  );
});
