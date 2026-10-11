import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { page } from "@vitest/browser/context";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowSpeakerIdentification from "./FlowSpeakerIdentification.svelte";

afterEach(cleanup);

// The space's standard: what a flow without a choice uses.
const vemsa = {
  id: "s-1",
  name: "Vemsa Sundsvall",
  meets_security_classification: true,
  available: true,
  is_standard: true
};
const second = {
  id: "s-2",
  name: "Talare test",
  meets_security_classification: true,
  available: true,
  is_standard: false
};
const standardOption = m.flow_transcription_speakers_standard({ name: vemsa.name });

function renderRow(props: {
  services?: (typeof vemsa)[];
  labels?: boolean;
  pickedId?: string | null;
  onPick?: (serviceId: string | null) => void;
}) {
  return render(FlowSpeakerIdentification, {
    services: props.services ?? [],
    labels: props.labels ?? true,
    pickedId: props.pickedId ?? null,
    maxSpeakers: null,
    disabled: false,
    onLabelsChange: vi.fn(),
    onPick: props.onPick ?? vi.fn(),
    onMaxSpeakersChange: vi.fn()
  });
}

const picker = () => page.getByLabelText(m.flow_transcription_speakers_service_label());

async function choose(option: string) {
  await picker().click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

describe("speaker identification", () => {
  it("is greyed out with an explanation when the space has no usable service", () => {
    renderRow({
      services: [
        { ...vemsa, available: false },
        { ...second, meets_security_classification: false }
      ]
    });

    const toggle = screen.getByRole("switch", { name: m.flow_transcription_diarization() });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(
      screen.getByRole("button", { name: m.flow_transcription_speakers_unavailable_label() })
    ).toBeInTheDocument();
  });

  it("names the space's only service instead of asking", () => {
    renderRow({ services: [vemsa] });

    expect(
      screen.getByText(m.flow_transcription_speakers_by({ name: vemsa.name }))
    ).toBeInTheDocument();
    expect(screen.queryByText(m.flow_transcription_speakers_service_label())).toBeNull();
  });

  it("uses the space's standard until the flow chooses another", async () => {
    const onPick = vi.fn();
    // The space says which service is its standard; it need not be listed first.
    renderRow({ services: [second, vemsa], onPick });

    await expect.element(picker()).toHaveTextContent(standardOption);
    await picker().click();
    await expect.element(page.getByRole("option").first()).toHaveTextContent(standardOption);
    await page.getByRole("option", { name: second.name, exact: true }).click();

    expect(onPick.mock.calls).toEqual([[second.id]]);
  });

  it("goes back to the space's standard by clearing the flow's choice", async () => {
    const onPick = vi.fn();
    renderRow({ services: [vemsa, second], pickedId: second.id, onPick });

    await expect.element(picker()).toHaveTextContent(second.name);
    await choose(standardOption);

    expect(onPick.mock.calls).toEqual([[null]]);
  });

  it("shows a choice of the space's only service, so it can be cleared", async () => {
    const onPick = vi.fn();
    renderRow({ services: [vemsa], pickedId: vemsa.id, onPick });

    // Chosen, not merely used: the flow stays on it whatever the space's standard becomes.
    await expect.element(picker()).toHaveTextContent(vemsa.name);
    await choose(standardOption);

    expect(onPick.mock.calls).toEqual([[null]]);
  });

  it("says when the picked service is no longer usable, and lets the standard replace it", async () => {
    const onPick = vi.fn();
    renderRow({ services: [vemsa], pickedId: "gone", onPick });

    expect(screen.getByText(m.flow_transcription_speakers_pick_unavailable())).toBeInTheDocument();
    // The lost choice is not replaced on the author's behalf.
    await expect.element(picker()).toHaveTextContent(m.flow_transcription_speakers_choose());
    await choose(standardOption);

    expect(onPick.mock.calls).toEqual([[null]]);
  });

  it("shows nothing more while labels are off", () => {
    renderRow({ services: [vemsa], labels: false });

    expect(screen.queryByText(m.flow_transcription_speakers_by({ name: vemsa.name }))).toBeNull();
  });
});

describe("speaker count", () => {
  it("is automatic when empty and saves a whole number as the maximum", async () => {
    const onMaxSpeakersChange = vi.fn();
    render(FlowSpeakerIdentification, {
      services: [vemsa],
      labels: true,
      pickedId: null,
      maxSpeakers: null,
      disabled: false,
      onLabelsChange: vi.fn(),
      onPick: vi.fn(),
      onMaxSpeakersChange
    });
    const input = screen.getByLabelText(m.flow_transcription_speakers_max_label());

    expect(input).toHaveAttribute("placeholder", m.flow_transcription_speakers_max_placeholder());
    await fireEvent.change(input, { target: { value: "4" } });
    await fireEvent.change(input, { target: { value: "0" } });
    await fireEvent.change(input, { target: { value: "" } });

    expect(onMaxSpeakersChange.mock.calls).toEqual([[4], [null]]);
  });

  it("refuses a count that is not a whole number from 1 and shows the saved one again", async () => {
    const onMaxSpeakersChange = vi.fn();
    render(FlowSpeakerIdentification, {
      services: [vemsa],
      labels: true,
      pickedId: null,
      maxSpeakers: 3,
      disabled: false,
      onLabelsChange: vi.fn(),
      onPick: vi.fn(),
      onMaxSpeakersChange
    });
    const input = screen.getByLabelText(m.flow_transcription_speakers_max_label());

    for (const refused of ["0", "2.5"]) {
      await fireEvent.change(input, { target: { value: refused } });
      expect(input).toHaveValue(3);
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByRole("alert")).toHaveTextContent(
        m.flow_transcription_speakers_max_invalid()
      );
    }
    await fireEvent.change(input, { target: { value: "5" } });

    expect(onMaxSpeakersChange.mock.calls).toEqual([[5]]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lets the author turn labels off when the picked service is gone and none is left", async () => {
    // Publishing would refuse the lost pick; turning labels off is the way out.
    const onLabelsChange = vi.fn();
    render(FlowSpeakerIdentification, {
      services: [{ ...vemsa, available: false }],
      labels: true,
      pickedId: vemsa.id,
      maxSpeakers: null,
      disabled: false,
      onLabelsChange,
      onPick: vi.fn(),
      onMaxSpeakersChange: vi.fn()
    });
    const toggle = screen.getByRole("switch", { name: m.flow_transcription_diarization() });

    expect(toggle).toBeEnabled();
    expect(toggle).toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent(
      m.flow_transcription_speakers_pick_unavailable_none()
    );
    await fireEvent.click(toggle);
    expect(onLabelsChange).toHaveBeenCalledWith(false);
  });
});
