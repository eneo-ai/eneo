// @vitest-environment jsdom
import { createRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Link from "@/lib/link";
import { expectNoAxeViolations } from "@/test/axe";
import { renderWithRouter } from "@/test/router";
import { SkillForm } from "./skill-form";

vi.unmock("@/lib/link");

async function renderForm(onSubmit = vi.fn(async () => {})) {
  return renderWithRouter(<Link href="/done">Leave editor</Link>, {
    route: "/edit",
    routes: (root) => [
      createRoute({
        getParentRoute: () => root,
        path: "/edit",
        component: () => (
          <SkillForm
            mode="revision"
            initialValue={{
              display_name: "Original",
              description: "Description",
              instructions: "Instructions"
            }}
            onSubmit={onSubmit}
          />
        )
      }),
      createRoute({ getParentRoute: () => root, path: "/done", component: () => <h1>Done</h1> })
    ]
  });
}
const click = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
async function leave() {
  const link = screen.getByRole("link", { name: "Leave editor" });
  link.focus();
  await act(async () => {
    fireEvent.click(link);
  });
}
function edit() {
  fireEvent.change(screen.getByRole("textbox", { name: "Namn" }), { target: { value: "Changed" } });
}

it("keeps skill edits on Cancel or Escape and leaves only after confirmation", async () => {
  const { router } = await renderForm();
  edit();
  await leave();
  const dialog = await screen.findByRole("alertdialog", { name: "Lämna sidan?" });
  expect(router.state.location.pathname).toBe("/edit");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Avbryt" }));
  await expectNoAxeViolations(dialog);
  await click("Avbryt");
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect((screen.getByRole("textbox", { name: "Namn" }) as HTMLInputElement).value).toBe("Changed");
  expect(document.activeElement).toBe(screen.getByRole("link", { name: "Leave editor" }));
  await leave();
  fireEvent.keyDown(await screen.findByRole("alertdialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(router.state.location.pathname).toBe("/edit");
  await leave();
  await screen.findByRole("alertdialog");
  await click("Lämna utan att spara");
  await screen.findByRole("heading", { name: "Done" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it("retains the guard after a failed save and releases it after a successful retry", async () => {
  const onSubmit = vi.fn(async () => {}).mockRejectedValueOnce(new Error("Unavailable"));
  await renderForm(onSubmit);
  edit();
  await click("Spara ändringar");
  await screen.findByRole("alert");
  await leave();
  await screen.findByRole("alertdialog");
  await click("Avbryt");
  expect((screen.getByRole("textbox", { name: "Namn" }) as HTMLInputElement).value).toBe("Changed");
  await click("Spara ändringar");
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Kassera alla ändringar" })).toBeNull()
  );
  expect(onSubmit).toHaveBeenCalledTimes(2);
  await leave();
  await screen.findByRole("heading", { name: "Done" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
});
