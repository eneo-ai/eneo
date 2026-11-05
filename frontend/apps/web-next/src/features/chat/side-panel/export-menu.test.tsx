// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { DocumentExport, DocumentExportAvailability } from "./document-export";
import { ExportMenu } from "./export-menu";

afterEach(cleanup);

it("retries a failed availability check inside the open menu without duplicate requests", async () => {
  let finish!: (value: DocumentExportAvailability) => void;
  const availability = vi
    .fn<DocumentExport["availability"]>()
    .mockRejectedValueOnce(new Error("Offline"))
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
  renderInApp(
    <ExportMenu
      fileId="document"
      title="Rapport"
      namesImages={false}
      compact={false}
      exporting={{ availability, exportAs: async () => new Blob() }}
      onSaveOriginal={vi.fn()}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Exportera" }));
  const retry = await screen.findByRole("menuitem", { name: /Försök igen/ });
  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(availability).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("menu").contains(document.activeElement)).toBe(true);
  fireEvent.click(retry);
  expect(availability).toHaveBeenCalledTimes(2);
  await act(async () => finish({ docx: { available: true }, pdf: { available: true } }));
  await waitFor(() =>
    expect(screen.getByRole("menuitem", { name: /^Word/ }).getAttribute("aria-disabled")).not.toBe(
      "true"
    )
  );
  expect(screen.getByRole("menu")).toBeTruthy();
});
