// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { PublishDialog } from "./publish-dialog";

afterEach(cleanup);

function show(pending: boolean, onOpenChange = vi.fn()) {
  renderInApp(
    <PublishDialog
      open
      onOpenChange={onOpenChange}
      name="Avtalsguiden"
      published={false}
      pending={pending}
      publishHint="Synlig för alla i ytan."
      onConfirm={() => {}}
    />
  );
  return onOpenChange;
}

it("stays open on Escape while publishing", async () => {
  const onOpenChange = show(true);
  const dialog = await screen.findByRole("alertdialog", { name: /Avtalsguiden/ });

  fireEvent.keyDown(dialog, { key: "Escape" });

  expect(onOpenChange).not.toHaveBeenCalled();
  expect(screen.getByText("Synlig för alla i ytan.")).toBeDefined();
});

it("closes on Escape when idle", async () => {
  const onOpenChange = show(false);

  fireEvent.keyDown(await screen.findByRole("alertdialog"), { key: "Escape" });

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});
