// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { ResourceAttachmentsSection } from "./resource-attachments-section";

vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

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
