import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { page } from "@vitest/browser/context";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowSpeakerIdentification from "./FlowSpeakerIdentification.svelte";

afterEach(cleanup);

const vemsa = {
  id: "s-1",
  name: "Vemsa Sundsvall",
  meets_security_classification: true,
  available: true,
  is_default: false
};
const second = {
  id: "s-2",
  name: "Talare test",
  meets_security_classification: true,
  available: true,
  is_default: false
};

function renderRow(props: {
  services?: (typeof vemsa)[];
  labels?: boolean;
  required?: boolean;
  pickedId?: string | null;
  maxSpeakers?: number | null;
  onLabelsChange?: (labels: boolean) => void;
  onPick?: (serviceId: string) => void;
  onMaxSpeakersChange?: (maxSpeakers: number | null) => void;
}) {
  return render(FlowSpeakerIdentification, {
    services: props.services ?? [],
    labels: props.labels ?? true,
    required: props.required ?? false,
    pickedId: props.pickedId ?? null,
    maxSpeakers: props.maxSpeakers ?? null,
    disabled: false,
    onLabelsChange: props.onLabelsChange ?? vi.fn(),
    onPick: props.onPick ?? vi.fn(),
    onMaxSpeakersChange: props.onMaxSpeakersChange ?? vi.fn()
  });
}

const picker = () => page.getByLabelText(m.flow_transcription_speakers_service_label());

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

  it("asks which service identifies speakers, also when the space has only one", async () => {
    const onPick = vi.fn();
    renderRow({ services: [vemsa], onPick });

    // Nothing is chosen for the flow, and nothing depends on a choice yet.
    await expect.element(picker()).toHaveTextContent(m.flow_transcription_speakers_choose());
    await expect
      .element(picker())
      .toHaveAccessibleDescription(m.flow_transcription_speakers_choose_hint());
    expect(screen.queryByLabelText(m.flow_transcription_speakers_max_label())).toBeNull();

    await picker().click();
    await expect.element(page.getByRole("option")).toHaveTextContent(vemsa.name);
    await page.getByRole("option", { name: vemsa.name, exact: true }).click();

    expect(onPick.mock.calls).toEqual([[vemsa.id]]);
  });

  it("shows the flow's choice and offers the space's other services", async () => {
    const onPick = vi.fn();
    renderRow({ services: [vemsa, second], pickedId: second.id, onPick });

    await expect.element(picker()).toHaveTextContent(second.name);
    expect(screen.queryByText(m.flow_transcription_speakers_choose_hint())).toBeNull();
    await picker().click();
    expect(page.getByRole("option").elements()).toHaveLength(2);
    await page.getByRole("option", { name: vemsa.name, exact: true }).click();

    expect(onPick.mock.calls).toEqual([[vemsa.id]]);
  });

  it("names the organisation's default, in the list and as the flow's choice", async () => {
    const standard = { ...second, is_default: true };
    const label = m.flow_transcription_speakers_default_option({ name: standard.name });
    renderRow({ services: [vemsa, standard], pickedId: standard.id });

    // Filled in by the default or chosen by hand, it reads the same: the
    // author sees which service is the organisation's default.
    await expect.element(picker()).toHaveTextContent(label);
    await picker().click();
    await expect.element(page.getByRole("option", { name: label, exact: true })).toBeVisible();
    await expect.element(page.getByRole("option", { name: vemsa.name, exact: true })).toBeVisible();
  });

  it.each([
    {
      case: "switched off",
      services: [{ ...vemsa, available: false }, second],
      reason: m.flow_transcription_speakers_lost_disabled({ name: vemsa.name }),
      shown: vemsa.name
    },
    {
      case: "below the space's classification",
      services: [{ ...vemsa, meets_security_classification: false }, second],
      reason: m.flow_transcription_speakers_lost_classification({ name: vemsa.name }),
      shown: vemsa.name
    },
    {
      case: "no longer in the space",
      services: [second],
      reason: m.flow_transcription_speakers_lost_removed(),
      shown: m.flow_transcription_speakers_choose()
    }
  ])("keeps a choice that is $case and says why", async ({ services, reason, shown }) => {
    const onPick = vi.fn();
    renderRow({ services, pickedId: vemsa.id, onPick });

    // The other usable service is offered, never chosen in its place.
    await expect.element(picker()).toHaveTextContent(shown);
    await expect.element(picker()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("status")).toHaveTextContent(
      `${reason} ${m.flow_transcription_speakers_lost_choose_other()}`
    );
    expect(onPick).not.toHaveBeenCalled();
  });

  it("lets the author turn labels off when the chosen service is lost and none is left", async () => {
    // Publishing would refuse the lost choice; turning labels off is the way out.
    const onLabelsChange = vi.fn();
    renderRow({ services: [{ ...vemsa, available: false }], pickedId: vemsa.id, onLabelsChange });
    const toggle = screen.getByRole("switch", { name: m.flow_transcription_diarization() });

    expect(toggle).toBeEnabled();
    expect(toggle).toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent(
      `${m.flow_transcription_speakers_lost_disabled({ name: vemsa.name })} ${m.flow_transcription_speakers_lost_no_other()}`
    );
    await fireEvent.click(toggle);
    expect(onLabelsChange).toHaveBeenCalledWith(false);
  });

  it("stays on and asks for a service while a step names the speakers", async () => {
    const onLabelsChange = vi.fn();
    renderRow({ services: [vemsa], labels: false, required: true, onLabelsChange });
    const toggle = screen.getByRole("switch", { name: m.flow_transcription_diarization() });

    // The step needs the labels, so the switch has nothing to decide.
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    expect(screen.getByText(m.flow_transcription_speakers_required_note())).toBeInTheDocument();
    await expect
      .element(picker())
      .toHaveAccessibleDescription(m.flow_transcription_speakers_choose_hint_required());
  });

  it.each([
    { case: "has no service", services: [], labels: true },
    { case: "has no service, with the flow's own setting off", services: [], labels: false },
    {
      case: "has only services it cannot use",
      services: [
        { ...vemsa, available: false },
        { ...second, meets_security_classification: false }
      ],
      labels: true
    },
    {
      case: "has only services it cannot use, with the flow's own setting off",
      services: [{ ...vemsa, available: false }],
      labels: false
    }
  ])(
    "stays on and says what is missing when a step names the speakers and the space $case",
    ({ services, labels }) => {
      renderRow({ services, labels, required: true });
      const toggle = screen.getByRole("switch", { name: m.flow_transcription_diarization() });

      // The flow needs the labels: it is not shown as switched off or as optional.
      expect(toggle).toBeChecked();
      expect(toggle).toBeDisabled();
      expect(screen.getByText(m.flow_transcription_speakers_required_note())).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        m.flow_transcription_speakers_required_no_service()
      );
      expect(screen.queryByText(m.flow_transcription_speakers_service_label())).toBeNull();
    }
  );

  it("offers no way out through the switch when a step needs the lost service", () => {
    renderRow({
      services: [{ ...vemsa, available: false }],
      required: true,
      pickedId: vemsa.id
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      `${m.flow_transcription_speakers_lost_disabled({ name: vemsa.name })} ${m.flow_transcription_speakers_lost_no_other_required()}`
    );
  });

  it("shows nothing more while labels are off", () => {
    renderRow({ services: [vemsa], labels: false, pickedId: vemsa.id });

    expect(screen.queryByText(m.flow_transcription_speakers_service_label())).toBeNull();
  });
});

describe("speaker count", () => {
  it("is automatic when empty and saves a whole number as the maximum", async () => {
    const onMaxSpeakersChange = vi.fn();
    renderRow({ services: [vemsa], pickedId: vemsa.id, onMaxSpeakersChange });
    const input = screen.getByLabelText(m.flow_transcription_speakers_max_label());

    expect(input).toHaveAttribute("placeholder", m.flow_transcription_speakers_max_placeholder());
    await fireEvent.change(input, { target: { value: "4" } });
    await fireEvent.change(input, { target: { value: "0" } });
    await fireEvent.change(input, { target: { value: "" } });

    expect(onMaxSpeakersChange.mock.calls).toEqual([[4], [null]]);
  });

  it("refuses a count that is not a whole number from 1 and shows the saved one again", async () => {
    const onMaxSpeakersChange = vi.fn();
    renderRow({ services: [vemsa], pickedId: vemsa.id, maxSpeakers: 3, onMaxSpeakersChange });
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
});
