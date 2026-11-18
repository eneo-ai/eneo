// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { PolicyConfirmDialog } from "./policy-confirm-dialog";

afterEach(cleanup);

it("is an alertdialog that stays open on Escape while saving", async () => {
  const onCancel = vi.fn();
  renderInApp(
    <PolicyConfirmDialog
      pending={["governance_confirm_mcp_disabled"]}
      saving
      onCancel={onCancel}
      onConfirm={() => {}}
    />
  );
  const dialog = await screen.findByRole("alertdialog");

  expect(dialog.textContent).toContain(
    "Alla MCP-servrar inaktiveras i den personliga assistenten."
  );
  fireEvent.keyDown(dialog, { key: "Escape" });

  expect(onCancel).not.toHaveBeenCalled();
});

it("cancels on Escape when idle", async () => {
  const onCancel = vi.fn();
  renderInApp(
    <PolicyConfirmDialog
      pending={["governance_confirm_mcp_disabled"]}
      saving={false}
      onCancel={onCancel}
      onConfirm={() => {}}
    />
  );

  fireEvent.keyDown(await screen.findByRole("alertdialog"), { key: "Escape" });

  await waitFor(() => expect(onCancel).toHaveBeenCalled());
});
