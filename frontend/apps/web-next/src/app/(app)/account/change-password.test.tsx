// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ChangePasswordCard } from "./change-password.client";

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;
const save = () => screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement;

/** What Tab visits, in order (no positive tabindex is used). */
function tabStops(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>("input, button")].filter(
    (element) => element.tabIndex >= 0 && !(element as HTMLButtonElement).disabled
  );
}

afterEach(() => vi.clearAllMocks());

describe("ChangePasswordCard", () => {
  it("gives password managers the account and the tokens they fill by", async () => {
    const { container } = renderInApp(<ChangePasswordCard />);

    // The login form's `username` is the email.
    const account = container.querySelector<HTMLInputElement>('input[autocomplete="username"]');
    expect(account?.value).toBe("anna.lind@example.se");
    expect(account?.getAttribute("aria-hidden")).toBe("true");
    expect(account?.tabIndex).toBe(-1);

    expect(field(/^Nuvarande lösenord/).getAttribute("autocomplete")).toBe("current-password");
    for (const input of [field(/^Nytt lösenord/), field(/^Bekräfta lösenord/)]) {
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("new-password");
    }
    // The length rule comes before the field (WCAG 3.3.2).
    const hint = within(container).getByText("Behöver vara minst 7 tecken långt");
    expect(field(/^Nytt lösenord/).getAttribute("aria-describedby")).toContain(hint.id);
    await expectNoAxeViolations(container);
  });

  it("is filled in field by field from the keyboard", () => {
    const { container } = renderInApp(<ChangePasswordCard />);
    fireEvent.change(field(/^Nuvarande lösenord/), { target: { value: "gammalt-lösen" } });
    fireEvent.change(field(/^Nytt lösenord/), { target: { value: "nytt-lösen-1" } });
    fireEvent.change(field(/^Bekräfta lösenord/), { target: { value: "nytt-lösen-1" } });

    expect(tabStops(container)).toEqual([
      field(/^Nuvarande lösenord/),
      field(/^Nytt lösenord/),
      field(/^Bekräfta lösenord/),
      save()
    ]);
  });

  it("says the new entries differ at the confirmation, and saves once they match", async () => {
    api.POST.mockReturnValue(new Promise(() => {}));
    const { container } = renderInApp(<ChangePasswordCard />);
    // Astryx's live region repeats the error for a while: read the field's own.
    const text = within(container);
    fireEvent.change(field(/^Nuvarande lösenord/), { target: { value: "gammalt-lösen" } });
    fireEvent.change(field(/^Nytt lösenord/), { target: { value: "nytt-lösen-1" } });
    field(/^Bekräfta lösenord/).focus();
    fireEvent.change(field(/^Bekräfta lösenord/), { target: { value: "nytt-lösen-2" } });

    expect(save().disabled).toBe(true);
    // Not while it is typed…
    expect(field(/^Bekräfta lösenord/).getAttribute("aria-invalid")).toBeNull();

    // …but once it is left.
    fireEvent.blur(field(/^Bekräfta lösenord/));
    const error = text.getByText("Lösenorden matchar inte");
    expect(field(/^Bekräfta lösenord/).getAttribute("aria-invalid")).toBe("true");
    expect(field(/^Bekräfta lösenord/).getAttribute("aria-describedby")).toContain(error.id);
    await expectNoAxeViolations(container);

    fireEvent.change(field(/^Bekräfta lösenord/), { target: { value: "nytt-lösen-1" } });
    expect(text.queryByText("Lösenorden matchar inte")).toBeNull();
    expect(save().disabled).toBe(false);

    fireEvent.submit(save().closest("form")!);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/users/me/password/", {
        body: { current_password: "gammalt-lösen", new_password: "nytt-lösen-1" }
      })
    );
  });

  it("keeps the save button off until both passwords have 7 characters", () => {
    renderInApp(<ChangePasswordCard />);
    fireEvent.change(field(/^Nuvarande lösenord/), { target: { value: "gammalt-lösen" } });
    fireEvent.change(field(/^Nytt lösenord/), { target: { value: "kort" } });
    fireEvent.change(field(/^Bekräfta lösenord/), { target: { value: "kort" } });

    expect(save().disabled).toBe(true);
  });
});
