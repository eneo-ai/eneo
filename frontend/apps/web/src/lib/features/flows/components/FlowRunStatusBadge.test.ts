import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";

describe("FlowRunStatusBadge", () => {
  it("renders a dotted small status by default", () => {
    const { body } = render(FlowRunStatusBadge, { props: { status: "completed" } });

    expect(body).toContain(m.flow_run_status_completed());
    expect(body).toContain("text-xs");
    expect(body).toContain("gap-2");
    expect(body).toContain('aria-hidden="true"');
    expect(body).toContain("bg-positive-default");
    expect(body).not.toContain("animate-pulse");
  });

  it("can render text-only status without a dot", () => {
    const { body } = render(FlowRunStatusBadge, {
      props: {
        status: "completed",
        showDot: false,
        size: "md"
      }
    });

    expect(body).toContain(m.flow_run_status_completed());
    expect(body).toContain("text-sm");
    expect(body).toContain("gap-2");
    expect(body).not.toContain('aria-hidden="true"');
    expect(body).not.toContain("bg-positive-default");
    expect(body).not.toContain("rounded-full");
  });

  it("renders compact step-card status at xs size", () => {
    const { body } = render(FlowRunStatusBadge, {
      props: { status: "failed", size: "xs" }
    });

    expect(body).toContain("text-xs");
    expect(body).toContain("gap-1.5");
    expect(body).toContain("bg-negative-default");
  });

  it("renders cancelled status with warning visuals", () => {
    const { body } = render(FlowRunStatusBadge, { props: { status: "cancelled" } });

    expect(body).toContain(m.flow_run_status_cancelled());
    expect(body).toContain("text-warning-stronger");
    expect(body).toContain("bg-warning-default");
    expect(body).not.toContain("animate-pulse");
  });

  it("renders awaiting review status without the running pulse", () => {
    const { body } = render(FlowRunStatusBadge, { props: { status: "awaiting_review" } });

    expect(body).toContain(m.flow_run_status_awaiting_review());
    expect(body).toContain("text-accent-stronger");
    expect(body).toContain("bg-accent-default");
    expect(body).not.toContain("animate-pulse");
  });

  it("pulses running status by default", () => {
    const { body } = render(FlowRunStatusBadge, { props: { status: "running" } });

    expect(body).toContain("animate-pulse");
  });

  it("can suppress the running pulse", () => {
    const { body } = render(FlowRunStatusBadge, {
      props: { status: "running", pulsing: false }
    });

    expect(body).not.toContain("animate-pulse");
  });

  it("forwards caller classes to the outer badge element", () => {
    const { body } = render(FlowRunStatusBadge, {
      props: { status: "completed", class: "shrink-0" }
    });

    expect(body).toContain("shrink-0");
  });
});
