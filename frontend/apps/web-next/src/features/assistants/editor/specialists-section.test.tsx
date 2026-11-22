// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { SpecialistsSection } from "./specialists-section";

const save = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => ({ mutateAsync: save })
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: makeSpace({
      assistants: [
        { id: "parent", name: "Samordnaren" },
        { id: "legal", name: "Juridik" }
      ]
    })
  })
}));
afterEach(() => {
  cleanup();
  save.mockClear();
});
const existing = [
  { id: "it", handle: "IT", default_description: "IT-policy", user_description: "Gamla rollen" }
];

async function choose(name: string) {
  fireEvent.click(screen.getByRole("button", { name: "Specialister" }));
  expect(screen.queryByRole("option", { name: "Samordnaren" })).toBeNull();
  fireEvent.click(await screen.findByRole("option", { name }));
}

it("keeps existing assignments when adding a specialist and editing its routing description", async () => {
  const { container } = renderInApp(
    <SpecialistsSection
      assistant={{ id: "parent", permissions: ["edit"], specialists: existing }}
      supportsTools
    />
  );
  expect(screen.getByText("Gamla rollen")).toBeTruthy();
  await choose("Juridik");
  fireEvent.click(screen.getByRole("button", { name: "Lägg till specialist" }));
  expect(save).not.toHaveBeenCalled();
  const field = screen.getByRole("textbox", { name: /Vad den ska rådfrågas om/ });
  fireEvent.change(field, { target: { value: "Avtal" } });
  await expectNoAxeViolations(container);
  fireEvent.click(screen.getByRole("button", { name: "Lägg till specialist" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith({
      specialists: [
        { id: "it", user_description: "Gamla rollen" },
        { id: "legal", user_description: "Avtal" }
      ]
    })
  );
  await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  await choose("IT");
  const role = screen.getByRole("textbox", { name: /Vad den ska rådfrågas om/ });
  fireEvent.change(role, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith({ specialists: [{ id: "it", user_description: null }] })
  );
  await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  await choose("IT");
  fireEvent.click(screen.getByRole("button", { name: "Ta bort specialist" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith({ specialists: [] }));
});

it.each([
  { label: "Spara", focus: "button" },
  { label: "Ta bort specialist", focus: "button" },
  { label: "Spara", focus: "textbox" }
])(
  "keeps focus on the $focus and accepts one edit while $label is pending",
  async ({ label, focus }) => {
    const request = Promise.withResolvers<object>();
    save.mockReturnValueOnce(request.promise);
    renderInApp(
      <SpecialistsSection
        assistant={{ id: "parent", permissions: ["edit"], specialists: existing }}
        supportsTools
      />
    );
    await choose("IT");
    const button = screen.getByRole("button", { name: label });
    const other = screen.getByRole("button", {
      name: label === "Spara" ? "Ta bort specialist" : "Spara"
    });
    const role = screen.getByRole("textbox");
    const origin = focus === "textbox" ? role : button;
    origin.focus();
    fireEvent.click(button);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(role).toHaveProperty("readOnly", true);
    expect(document.activeElement).toBe(origin);
    fireEvent.click(button);
    fireEvent.click(other);
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => request.resolve({}));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Specialister" }));
  }
);

it("shows a reader the configured specialists without editing controls", () => {
  renderInApp(
    <SpecialistsSection
      assistant={{ id: "parent", permissions: ["read"], specialists: existing }}
      supportsTools
    />
  );
  expect(screen.getByText("Gamla rollen")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Specialister" })).toBeNull();
});
