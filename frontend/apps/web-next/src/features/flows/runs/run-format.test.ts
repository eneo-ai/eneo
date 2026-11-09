import { describe, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { makeRunStep } from "./run-fixtures";
import { formatSeconds, stepInputFiles } from "./run-format";

describe("formatSeconds", () => {
  const t = (key: string, values: Record<string, string | number> = {}) =>
    (messages as Record<string, string>)[key]!.replace(/\{(\w+)\}/g, (_, name: string) =>
      String(values[name])
    );

  it("says seconds and minutes, and from an hour hours and minutes without the seconds", () => {
    expect(formatSeconds(45, t)).toBe("45 s");
    expect(formatSeconds(725, t)).toBe("12 min 5 s");
    expect(formatSeconds(3599, t)).toBe("59 min 59 s");
    expect(formatSeconds(13_115, t)).toBe("3 h 38 min");
  });
});

describe("stepInputFiles", () => {
  it("names each file in the order of the ids, and numbers the ones without a name", () => {
    const step = makeRunStep(1, {
      runtime_input_file_ids: ["file-a", "file-b", "file-c"],
      runtime_input_files: [
        { file_id: "file-c", name: "inspelning.m4a", mimetype: "audio/mp4" },
        { file_id: "file-a", name: "underlag.pdf", mimetype: "application/pdf" }
      ]
    });

    expect(stepInputFiles(step)).toEqual([
      { fileId: "file-a", name: "underlag.pdf", typeName: "PDF" },
      { fileId: "file-b", name: null, typeName: null },
      { fileId: "file-c", name: "inspelning.m4a", typeName: "M4A" }
    ]);
  });

  it("keeps a MIME type it has no name for, and reads a backend that names nothing", () => {
    expect(
      stepInputFiles(
        makeRunStep(1, {
          runtime_input_file_ids: ["file-a"],
          runtime_input_files: [{ file_id: "file-a", name: "data", mimetype: "application/x-foo" }]
        })
      )
    ).toEqual([{ fileId: "file-a", name: "data", typeName: "application/x-foo" }]);
    expect(
      stepInputFiles(
        makeRunStep(1, { runtime_input_file_ids: ["file-a"], runtime_input_files: null })
      )
    ).toEqual([{ fileId: "file-a", name: null, typeName: null }]);
  });
});
