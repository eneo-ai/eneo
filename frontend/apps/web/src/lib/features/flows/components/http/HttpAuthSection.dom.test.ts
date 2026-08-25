import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

import HttpAuthSection from "./HttpAuthSection.svelte";
import type { HttpAuth } from "./httpConfigTypes";

const SECRET_SENTINEL = { $secret: "stored" } as const;

function renderAuthSection(auth: HttpAuth, onAuthChange = vi.fn()) {
  render(HttpAuthSection, {
    props: { auth, isPublished: false, onAuthChange }
  });
  return onAuthChange;
}

afterEach(() => {
  cleanup();
});

describe("HttpAuthSection", () => {
  it("associates a visible label with every credential input", () => {
    renderAuthSection({ mode: "api_key", header_name: "X-API-Key", key: "" });

    expect(screen.getByLabelText(m.http_auth_header_name())).toBeTruthy();
    expect(screen.getByLabelText(m.http_auth_api_key_value())).toBeTruthy();
  });

  it("explains the stored secret and moves focus to the input on replace", async () => {
    const onAuthChange = vi.fn();
    const { rerender } = render(HttpAuthSection, {
      props: {
        auth: { mode: "bearer_token", token: SECRET_SENTINEL } satisfies HttpAuth,
        isPublished: false,
        onAuthChange
      }
    });

    screen.getByText(m.http_secret_stored_help());
    await fireEvent.click(screen.getByRole("button", { name: m.http_secret_replace() }));

    expect(onAuthChange).toHaveBeenCalledWith({ auth: { mode: "bearer_token", token: "" } });

    await rerender({
      auth: { mode: "bearer_token", token: "" },
      isPublished: false,
      onAuthChange
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByLabelText(m.http_auth_bearer()));
    });
  });
});
