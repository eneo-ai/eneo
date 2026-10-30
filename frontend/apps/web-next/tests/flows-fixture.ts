import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { apiPost, apiRequest, uniqueName } from "./helpers";

/** A published audio flow through the same API contracts as the manual editor. */
export async function audioFlow(page: Page, realtime = false) {
  await page.goto("/spaces/list");
  const spaceId = await apiPost(page, "/spaces/", { name: uniqueName("E2E audio") });
  const space = await apiRequest<Schema<"SpacePublic">>(page, `/spaces/${spaceId}/`);
  let modelId = space.transcription_models[0]?.id;
  if (realtime) {
    const providerId = await apiPost(page, "/admin/model-providers/", {
      name: uniqueName("E2E realtime"),
      provider_type: "vllm",
      credentials: { api_key: "e2e-realtime-fixture" },
      config: { endpoint: "http://e2e-mock-realtime:8201/v1" }
    });
    modelId = await apiPost(page, "/admin/tenant-models/transcription/", {
      provider_id: providerId,
      name: uniqueName("e2e-realtime"),
      display_name: "E2E realtime",
      supports_realtime: true
    });
    await apiRequest(page, `/spaces/${spaceId}/`, {
      method: "PATCH",
      body: { transcription_models: [{ id: modelId }] }
    });
  }
  if (!modelId) throw new Error("The E2E space has no seeded transcription model");
  const flow = await apiRequest<Schema<"FlowPublic">>(page, "/flows/", {
    method: "POST",
    body: { space_id: spaceId, name: uniqueName("E2E audio flow") }
  });
  const saved = await apiRequest<Schema<"FlowPublic">>(page, `/flows/${flow.id}/editor/`, {
    method: "PATCH",
    body: {
      expected_revision: flow.draft_revision,
      definition: {
        metadata_json: {
          wizard: {
            transcription_enabled: true,
            transcription_model: { id: modelId },
            transcription_language: "sv"
          }
        }
      },
      new_steps: [
        {
          name: "Transkribera",
          assistant: {},
          configuration: {
            input_source: "flow_input",
            input_type: "audio",
            output_mode: "transcribe_only",
            output_type: "text",
            input_config: {
              runtime_input: { enabled: true, required: true, input_format: "audio" }
            }
          }
        }
      ]
    } satisfies Schema<"FlowEditorUpdateRequest">
  });
  await apiRequest(page, `/flows/${flow.id}/publish/`, { method: "POST" });
  return {
    flowId: flow.id,
    stepId: saved.steps[0]!.id,
    url: `/spaces/${spaceId}/flows/${flow.id}`
  };
}

/** Valid mono PCM16 WAV bytes, including a real RIFF length for truncation checks. */
export function silenceWav(bytes: number): Buffer {
  const wav = Buffer.alloc(bytes);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(bytes - 8, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(16_000, 24);
  wav.writeUInt32LE(32_000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(bytes - 44, 40);
  return wav;
}
