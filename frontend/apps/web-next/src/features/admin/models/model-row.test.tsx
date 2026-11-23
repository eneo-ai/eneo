// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { ModelProvider } from "./model-providers";
import type { AdminModel } from "./models";
import { ModelRow } from "./model-row";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

it.each([
  [true, true, true],
  [false, false, false],
  // Marked, but its provider can no longer carry live text: not a capability now.
  [true, false, false]
])("marks live text among the capabilities: marked %s, streams %s", (marked, streams, on) => {
  renderInApp(
    <ModelRow
      model={
        {
          id: "t1",
          name: "pianissimo-sv",
          supports_realtime: marked,
          streams_live: streams
        } as AdminModel
      }
      kind="transcription"
      layout="list"
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  const capabilities = screen.queryByRole("list", { name: "Funktioner" });
  expect(capabilities?.textContent ?? "").toBe(on ? "Livetext" : "");
});

function liveRow(
  marked: boolean,
  streams: boolean,
  eligibility: ModelProvider["realtime_eligibility"],
  layout: "table" | "list" = "list"
) {
  const row = (
    <ModelRow
      model={
        {
          id: "t1",
          name: "pianissimo-sv",
          supports_realtime: marked,
          streams_live: streams
        } as AdminModel
      }
      kind="transcription"
      layout={layout}
      realtimeEligibility={eligibility}
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  return renderInApp(
    layout === "table" ? (
      <table>
        <tbody>{row}</tbody>
      </table>
    ) : (
      <ul>{row}</ul>
    )
  );
}

it.each([
  ["endpoint_required", "Ange adressen till servern eller gatewayen på leverantören."],
  ["unsupported_provider", "Välj en leverantör som stöds"],
  ["outbound_headers_configured", "Använd en leverantör utan utgående rubriker."]
] as const)(
  "says a marked model is not in use on a provider that cannot carry live text: %s",
  async (eligibility, reason) => {
    for (const layout of ["list", "table"] as const) {
      const { unmount } = liveRow(true, false, eligibility, layout);
      expect(screen.getByText("Markerad, används inte")).toBeTruthy();
      expect(screen.getByText(new RegExp(`^${reason}`))).toBeTruthy();
      await expectNoAxeViolations(document.body);
      unmount();
    }
  }
);

it.each([
  [true, true, "eligible"],
  [false, false, "endpoint_required"],
  [false, false, "eligible"]
] as const)(
  "says nothing about live text for a model that streams or is not marked: marked %s",
  (marked, streams, eligibility) => {
    liveRow(marked, streams, eligibility);
    expect(screen.queryByText("Markerad, används inte")).toBeNull();
    expect(screen.queryByText(/leverantör/)).toBeNull();
  }
);

it("locks a historical migrated model even when rendered directly", () => {
  const model = {
    id: "old",
    name: "gpt-4o",
    nickname: "Old model",
    is_org_enabled: false,
    is_locked: false,
    migrated_to_model_id: "replacement"
  } as AdminModel;
  renderInApp(
    <ModelRow
      model={model}
      kind="completion"
      layout="list"
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  const toggle = screen.getByRole("switch", { name: "Aktivera Old model" });
  expect(toggle.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(toggle);
  expect(api.POST).not.toHaveBeenCalled();
});
