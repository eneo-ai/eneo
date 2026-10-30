import { describe, expect, it } from "vitest";
import { makeRunStep } from "./run-fixtures";
import { stepInputFiles } from "./run-format";

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
