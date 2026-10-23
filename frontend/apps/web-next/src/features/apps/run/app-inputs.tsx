"use client";

import type { App } from "../apps";
import { AudioRecorderInput } from "./audio-recorder-input";
import { TextInput } from "./text-input";
import type { useAppRunInputs } from "./use-app-run";
import { UploadInput } from "./upload-input";

/** Renders one control per configured input field. */
export function AppInputs({
  app,
  inputs
}: {
  app: App;
  inputs: ReturnType<typeof useAppRunInputs>;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-4">
      {app.input_fields.map((field, index) => {
        const description = field.description ?? undefined;
        if (field.type === "text-field") {
          return (
            <TextInput
              key={index}
              value={inputs.text}
              description={description}
              onChange={inputs.setText}
            />
          );
        }
        if (field.type === "audio-recorder") {
          return (
            <AudioRecorderInput
              key={index}
              field={field}
              description={description}
              files={inputs.files}
              onAddFiles={inputs.addFiles}
              onRemoveFile={inputs.removeFile}
            />
          );
        }
        return (
          <UploadInput
            key={index}
            field={field}
            description={description}
            files={inputs.files}
            onAddFiles={inputs.addFiles}
            onRemoveFile={inputs.removeFile}
          />
        );
      })}
    </div>
  );
}
