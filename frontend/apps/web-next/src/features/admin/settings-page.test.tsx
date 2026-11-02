// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

vi.mock("./feature-toggles", () => ({ FeatureToggles: () => null }));
vi.mock("./audit/retention-policy-section", () => ({ RetentionPolicySection: () => null }));

import { AdminSettingsPage } from "./settings-page";

afterEach(cleanup);

it("starts with its title, without a trail above it, like its sibling admin pages", () => {
  renderInApp(<AdminSettingsPage />);
  expect(screen.getByRole("heading", { level: 1, name: "Inställningar" })).toBeTruthy();
  expect(screen.queryByRole("navigation")).toBeNull();
});
