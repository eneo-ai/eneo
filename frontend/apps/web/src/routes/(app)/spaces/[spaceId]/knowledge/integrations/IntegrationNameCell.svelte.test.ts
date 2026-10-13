import type { IntegrationKnowledge } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import "../../../../../../app.css";
import { expectNoAxeViolations } from "$lib/test/axe";
import IntegrationNameCell from "./IntegrationNameCell.svelte";

const knowledge = {
  id: "k-1",
  name: "Protokoll",
  original_name: "Protokoll KS",
  integration_type: "sharepoint"
} as IntegrationKnowledge;

describe("IntegrationNameCell", () => {
  it("links the name to the documents page and keeps the original name visible", async () => {
    render(IntegrationNameCell, { knowledge, href: "/spaces/s-1/knowledge/integrations/k-1" });
    const link = page.getByRole("link", { name: /Protokoll/ });
    await expect.element(link).toHaveAttribute("href", "/spaces/s-1/knowledge/integrations/k-1");
    await expect.element(link).toHaveTextContent("(Protokoll KS)");
    await expectNoAxeViolations();
  });

  it("is plain text without a link target", async () => {
    render(IntegrationNameCell, { knowledge });
    await expect.element(page.getByText(/Protokoll/)).toBeVisible();
    expect(page.getByRole("link").query()).toBeNull();
  });
});
