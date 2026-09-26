// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const env = vi.hoisted(() => ({ ACCESSIBILITY_STATEMENT_URL: undefined as string | undefined }));
vi.mock("@/lib/env", () => ({ env }));

import { PublicPage } from "./public-page";

afterEach(() => {
  cleanup();
  env.ACCESSIBILITY_STATEMENT_URL = undefined;
});

describe("PublicPage", () => {
  it("is one main landmark with the page's h1", async () => {
    const { container } = renderInApp(
      <PublicPage title="Inloggning misslyckades">
        <p>Försök igen.</p>
      </PublicPage>
    );
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Inloggning misslyckades");
    await expectNoAxeViolations(container, {});
  });

  it("links the organisation's accessibility statement when it is configured", () => {
    env.ACCESSIBILITY_STATEMENT_URL = "https://www.sundsvall.se/tillganglighetsredogorelse";
    renderInApp(
      <PublicPage title="Nästan klar!" footer={<button type="button">Aktivera</button>}>
        <p>Kontot är inte aktiverat.</p>
      </PublicPage>
    );
    expect(
      screen.getByRole("link", { name: "Tillgänglighetsredogörelse" }).getAttribute("href")
    ).toBe("https://www.sundsvall.se/tillganglighetsredogorelse");
    expect(screen.getByRole("button", { name: "Aktivera" })).toBeTruthy();
  });

  it("has no statement link when none is configured", () => {
    renderInApp(
      <PublicPage title="Välkommen till Eneo">
        <p>Logga in.</p>
      </PublicPage>
    );
    expect(screen.queryByRole("link")).toBeNull();
  });
});
