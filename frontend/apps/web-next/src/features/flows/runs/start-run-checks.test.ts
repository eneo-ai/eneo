import { describe, expect, it } from "vitest";
import { makeContract, makeInput } from "./run-fixtures";
import {
  fitRunLabel,
  reusedInput,
  RUN_LABEL_MAX_LENGTH,
  screenAudioFiles,
  startSummary,
  summaryIsEmpty,
  takesReusableInput,
  withRunLabel
} from "./start-run-checks";

describe("fitRunLabel", () => {
  it("keeps a name on one line", () => {
    expect(fitRunLabel("Ärende\n123\t4")).toEqual({ label: "Ärende 123 4", cut: false });
  });

  it("cuts a name past the limit, counting characters as the core does", () => {
    const long = "🙂".repeat(RUN_LABEL_MAX_LENGTH + 5);
    const fitted = fitRunLabel(long);
    expect(Array.from(fitted.label)).toHaveLength(RUN_LABEL_MAX_LENGTH);
    expect(fitted.cut).toBe(true);
    expect(fitRunLabel("🙂".repeat(RUN_LABEL_MAX_LENGTH)).cut).toBe(false);
  });
});

describe("withRunLabel", () => {
  it("sends the trimmed name and leaves a blank one out", () => {
    expect(withRunLabel({ expected_flow_version: 4 }, "  Ärende 123 ")).toEqual({
      expected_flow_version: 4,
      run_label: "Ärende 123"
    });
    expect(withRunLabel({ expected_flow_version: 4 }, "   ")).toEqual({
      expected_flow_version: 4
    });
  });
});

describe("screenAudioFiles", () => {
  const audio = { input_format: "audio" as const, max_duration_seconds: 3600 };
  const files = ["kort.mp3", "lang.mp3", "okand.mp3"].map(
    (name) => new File(["x"], name, { type: "audio/mpeg" })
  );
  const lengths: Record<string, number | null> = {
    "kort.mp3": 3600.9,
    "lang.mp3": 3601,
    "okand.mp3": null
  };
  const measure = (file: File) => Promise.resolve(lengths[file.name] ?? null);

  it("refuses only audio the browser measured as too long", async () => {
    const { accepted, refused } = await screenAudioFiles(audio, files, measure);
    expect(accepted.map((file) => file.name)).toEqual(["kort.mp3", "okand.mp3"]);
    expect(refused).toEqual([{ name: "lang.mp3", seconds: 3601, maxSeconds: 3600 }]);
  });

  it("passes other inputs and inputs without a limit straight through", async () => {
    const document = { input_format: "document" as const, max_duration_seconds: null };
    expect((await screenAudioFiles(document, files, measure)).accepted).toHaveLength(3);
    const unlimited = { input_format: "audio" as const, max_duration_seconds: null };
    expect((await screenAudioFiles(unlimited, files, measure)).refused).toEqual([]);
  });
});

describe("reusedInput", () => {
  const form = makeContract({
    form_fields: [
      { name: "arende", label: "Ärende", type: "text" },
      { name: "antal", label: "Antal", type: "number" },
      { name: "taggar", label: "Taggar", type: "multiselect", options: ["a", "b"] },
      { name: "lista", label: "Lista", type: "list" },
      { name: "ny", label: "Nytt fält", type: "text" }
    ],
    steps_requiring_input: [makeInput()]
  });

  it("gives each field of the form the value the run sent, and leaves a new field empty", () => {
    expect(
      reusedInput(form, {
        arende: "Bygglov",
        antal: 3,
        taggar: ["a", "b"],
        lista: "ett, två ,",
        borttaget: "x"
      })
    ).toEqual({
      values: { arende: "Bygglov", antal: "3", taggar: ["a", "b"], lista: ["ett", "två"], ny: "" },
      freeText: null
    });
  });

  it("reads an empty or unreadable value as empty", () => {
    expect(reusedInput(form, { arende: null, antal: { x: 1 }, taggar: "a" }).values).toEqual({
      arende: "",
      antal: "",
      taggar: ["a"],
      lista: [],
      ny: ""
    });
  });

  it("gives a free-text form the run's text, and keeps the form's when the run sent none", () => {
    const free = makeContract();
    expect(reusedInput(free, { text: "Hej" })).toEqual({ values: {}, freeText: "Hej" });
    expect(reusedInput(free, { arende: "Bygglov" }).freeText).toBeNull();
    expect(reusedInput(free, null).freeText).toBeNull();
  });
});

describe("takesReusableInput", () => {
  it("is true for a form with fields or a free text, and false for files only", () => {
    expect(takesReusableInput(makeContract())).toBe(true);
    expect(
      takesReusableInput(makeContract({ form_fields: [{ name: "a", label: "A", type: "text" }] }))
    ).toBe(true);
    expect(takesReusableInput(makeContract({ steps_requiring_input: [makeInput()] }))).toBe(false);
  });
});

describe("startSummary", () => {
  const contract = makeContract({
    form_fields: [
      { name: "arende", label: "Ärende", type: "text", required: true, order: 1 },
      { name: "taggar", label: "Taggar", type: "list", order: 2 },
      { name: "prio", label: "Prioritet", type: "select", options: ["Hög"], order: 3 }
    ],
    steps_requiring_input: [
      makeInput({ step_id: "step-2", step_order: 2, label: "Bilagor" }),
      makeInput({ step_id: "step-1", step_order: 1, label: "Brevet" })
    ]
  });

  it("lists the name, the fields given a value and each step's stored files in order", () => {
    const summary = startSummary(contract, {
      runLabel: "  Ärende 12 ",
      values: { arende: " Bygglov ", taggar: [" a ", "", "b"], prio: "" },
      freeText: "ignored",
      uploads: {
        "step-2": [
          { key: "k2", name: "bilaga.pdf", size: 5, mimetype: "", state: "done", fileId: "f2" }
        ],
        "step-1": [
          { key: "k1", name: "brev.pdf", size: 3, mimetype: "", state: "done", fileId: "f1" },
          { key: "k3", name: "trasig.pdf", size: 1, mimetype: "", state: "failed" }
        ]
      }
    });
    expect(summary.runLabel).toBe("Ärende 12");
    expect(summary.fields.map(({ field, value }) => [field.name, value])).toEqual([
      ["arende", "Bygglov"],
      ["taggar", "a, b"]
    ]);
    expect(summary.freeText).toBeNull();
    expect(
      summary.files.map(({ input, files }) => [input.step_id, files.map((f) => f.name)])
    ).toEqual([
      ["step-1", ["brev.pdf"]],
      ["step-2", ["bilaga.pdf"]]
    ]);
  });

  it("carries the free text of a form that takes one, and is empty when nothing is filled in", () => {
    const free = makeContract();
    const choices = { runLabel: " ", values: {}, uploads: {} };
    expect(startSummary(free, { ...choices, freeText: " Hej\nhej " }).freeText).toBe("Hej\nhej");
    expect(summaryIsEmpty(startSummary(free, { ...choices, freeText: "  " }))).toBe(true);
  });
});
