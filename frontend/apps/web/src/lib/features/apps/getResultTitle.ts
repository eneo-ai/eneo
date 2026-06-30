import type { AppRun } from "@eneo/eneo-js";

/** Generates a title for this run based on the inputted files' */
export function getResultTitle(run: Pick<AppRun, "input">) {
  let title = "";

  if (run.input.text) {
    title += "Input: " + run.input.text;
    if (run.input.files.length > 0) title += ", ";
  }

  run.input.files.forEach((file, index, self) => {
    title += file.name;
    if (index !== self.length - 1) title += ", ";
  });

  return title || "No input found to generate name";
}
