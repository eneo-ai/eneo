// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { RunFailure } from "./run-failure";
import { runStepAnchorId } from "./run-steps";
import type { RunErrorWithGuidance } from "./runs-api";

function error(overrides: Partial<RunErrorWithGuidance> = {}): RunErrorWithGuidance {
  return {
    schema_version: 1,
    code: "flow_step_timeout",
    message: "Step 2 exceeded its execution budget.",
    step_order: 2,
    details: null,
    retryable: false,
    user_action: "Check the run before retrying.",
    consumer_action: "Do not auto-retry.",
    ...overrides
  } as RunErrorWithGuidance;
}

afterEach(cleanup);

describe("RunFailure", () => {
  it("goes to the step the run stopped at and moves focus there", async () => {
    const { container } = renderInApp(
      <>
        <RunFailure error={error()} stepName={(order) => (order === 2 ? "Skriv svar" : null)} />
        <article id={runStepAnchorId(2)} tabIndex={-1} aria-label="Steg 2: Skriv svar" />
      </>
    );

    expect(screen.getByText("Körningen stannade i steg 2: Skriv svar.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_show_failed_step }));
    expect(document.activeElement).toBe(screen.getByRole("article"));
    await expectNoAxeViolations(container);
  });

  it("shows the catalog's sentence, and the taxonomy's guidance only when the catalog has none", () => {
    renderInApp(<RunFailure error={error()} />);
    expect(screen.getByText(messages.flow_error_flow_step_timeout)).toBeTruthy();
    expect(screen.queryByText("Check the run before retrying.")).toBeNull();
    cleanup();

    renderInApp(
      <RunFailure
        error={error({ code: "flow_new_code" as RunErrorWithGuidance["code"], step_order: null })}
      />
    );
    const guidance = screen.getByText("Check the run before retrying.");
    expect(guidance.getAttribute("lang")).toBe("en");
    expect(screen.queryByText(messages.flow_runs_error_unknown)).toBeNull();
  });

  it("keeps the guidance for API clients behind the technical detail", () => {
    renderInApp(<RunFailure error={error()} />);
    expect(screen.queryByText("Do not auto-retry.")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_run_extras_failure_technical })
    );
    expect(screen.getByText(messages.flow_run_journey_failure_consumer_action)).toBeTruthy();
    expect(screen.getByText("Do not auto-retry.")).toBeTruthy();
  });

  it("names the steps a refused review policy concerns", async () => {
    const { container } = renderInApp(
      <RunFailure
        error={error({ code: "flow_review_policy_invalid", step_order: null })}
        reviewSteps={[
          { step_order: 1, user_description: "Sammanfatta", review_policy: null },
          { step_order: 2, user_description: "Skriv svar", review_policy: { mode: "edit" } }
        ]}
      />
    );

    expect(screen.getByText(messages.flow_run_error_not_started)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_error_review_policy_invalid_action)).toBeTruthy();
    const list = screen.getByRole("list", {
      name: messages.flow_run_error_possible_affected_steps
    });
    expect(list.textContent).toBe("Steg 2: Skriv svar");
    await expectNoAxeViolations(container);
  });
});
