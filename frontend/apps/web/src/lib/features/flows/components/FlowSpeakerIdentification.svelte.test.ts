import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowSpeakerIdentification from "./FlowSpeakerIdentification.svelte";

afterEach(cleanup);

const vemsa = {
  id: "s-1",
  name: "Vemsa Sundsvall",
  meets_security_classification: true,
  available: true
};
const second = {
  id: "s-2",
  name: "Talare test",
  meets_security_classification: true,
  available: true
};

function renderRow(props: {
  services?: (typeof vemsa)[];
  labels?: boolean;
  pickedId?: string | null;
}) {
  return render(FlowSpeakerIdentification, {
    services: props.services ?? [],
    labels: props.labels ?? true,
    pickedId: props.pickedId ?? null,
    disabled: false,
    onLabelsChange: vi.fn(),
    onPick: vi.fn()
  });
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

  it("asks for a service when the space has several", () => {
    renderRow({ services: [vemsa, second] });

    expect(screen.getByText(m.flow_transcription_speakers_service_label())).toBeInTheDocument();
    expect(screen.getByText(m.flow_transcription_speakers_choose_hint())).toBeInTheDocument();
  });

  it("says when the picked service is no longer usable", () => {
    renderRow({ services: [vemsa], pickedId: "gone" });

    expect(screen.getByText(m.flow_transcription_speakers_pick_unavailable())).toBeInTheDocument();
  });

  it("shows nothing more while labels are off", () => {
    renderRow({ services: [vemsa], labels: false });

    expect(screen.queryByText(m.flow_transcription_speakers_by({ name: vemsa.name }))).toBeNull();
  });
});
