// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: {
          security_enabled: true,
          security_classifications: [
            { id: "c1", name: "Klass 1 · Öppen", description: null, security_level: 1 },
            { id: "c2", name: "Klass 2 · Intern", description: null, security_level: 2 }
          ]
        },
        response: new Response("{}")
      })
  }
}));

import { SecurityClassificationsPage } from "./classifications-page";

afterEach(cleanup);

describe("SecurityClassificationsPage", () => {
  it("names each classification's menu after the classification", async () => {
    renderInApp(<SecurityClassificationsPage />);

    expect(
      await screen.findByRole("button", { name: "Fler åtgärder för Klass 2 · Intern" })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Klass 1 · Öppen" })).toBeTruthy();
  });
});
