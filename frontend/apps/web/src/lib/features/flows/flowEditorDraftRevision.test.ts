import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EneoError } from "@eneo/eneo-js";
import type { Eneo, Flow, FlowStep } from "@eneo/eneo-js";

import { createFlowEditor } from "./FlowEditor";

vi.mock("$lib/components/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));

/*
 * The flow and its step assistants are one draft with one revision. A server
 * that holds that revision refuses any write sent with another one, the way
 * the flow and assistant endpoints do, and records every request.
 */

type Sent = { kind: "flow" | "assistant"; expected: number | undefined };

function staleRevision(expected: number | undefined): EneoError {
  const message = "Flödet har ändrats sedan det lästes in.";
  return new EneoError(
    message,
    "RESPONSE",
    400,
    0,
    {
      message,
      eneo_error_code: 9007,
      code: "stale_revision",
      context: { expected_revision: expected }
    },
    { endpoint: "/api/v1/flows/x" }
  );
}

function makeServer(revision: number, prompts: Record<string, string> = {}) {
  const sent: Sent[] = [];
  const refused: Sent[] = [];
  let inFlight = 0;
  let maxInFlight = 0;
  let hold: Promise<void> | null = null;
  const state = { revision };

  async function write<T>(entry: Sent, respond: (next: number) => T): Promise<T> {
    sent.push(entry);
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    try {
      if (hold) await hold;
      if (entry.expected !== state.revision) {
        refused.push(entry);
        throw staleRevision(entry.expected);
      }
      state.revision += 1;
      return respond(state.revision);
    } finally {
      inFlight -= 1;
    }
  }

  const flowUpdate = vi.fn(({ flow, update }: { flow: Flow; update: Record<string, unknown> }) => {
    const { expected_revision, ...changes } = update;
    return write({ kind: "flow", expected: expected_revision as number | undefined }, (next) => ({
      ...flow,
      ...changes,
      draft_revision: next
    }));
  });
  const assistantUpdate = vi.fn(
    ({ assistantId, update }: { assistantId: string; update: Record<string, unknown> }) => {
      const { expected_revision, ...changes } = update;
      return write(
        { kind: "assistant", expected: expected_revision as number | undefined },
        (next) => {
          const prompt = changes.prompt as { text: string } | undefined;
          if (prompt) prompts[assistantId] = prompt.text;
          return { id: assistantId, prompt: { text: prompts[assistantId] }, draft_revision: next };
        }
      );
    }
  );
  const eneo = {
    files: { delete: vi.fn() },
    flows: {
      update: flowUpdate,
      assistants: {
        create: vi.fn(async ({ name }: { name: string }) => ({
          id: `created-${name}`,
          prompt: null
        })),
        get: vi.fn(async ({ assistantId }: { assistantId: string }) => ({
          id: assistantId,
          prompt: { text: prompts[assistantId] ?? "", description: "" }
        })),
        update: assistantUpdate
      }
    },
    assistants: { listPrompts: vi.fn() }
  } as unknown as Eneo;

  return {
    eneo,
    sent,
    refused,
    state,
    prompts,
    maxInFlight: () => maxInFlight,
    /** Holds every request until the returned release is called. */
    hold(): () => void {
      let release!: () => void;
      hold = new Promise((resolve) => {
        release = () => {
          hold = null;
          resolve();
        };
      });
      return release;
    }
  };
}

function makeStep(order: number, overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: `step-${order}`,
    assistant_id: `assistant-${order}`,
    step_order: order,
    user_description: `Steg ${order}`,
    input_source: order === 1 ? "flow_input" : "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    ...overrides
  };
}

function makeFlow(revision: number, steps: FlowStep[] = [makeStep(1), makeStep(2)]): Flow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "tenant-1",
    space_id: "space-1",
    space_name: "Space",
    name: "Flöde",
    description: null,
    published_version: null,
    draft_revision: revision,
    step_count: steps.length,
    metadata_json: null,
    run_history_retention: {
      state: "configured",
      effective_days: 30,
      mode: "preserve",
      source: "organization",
      contributors: {
        organization: { mode: "preserve", days: 30 },
        space: null,
        flow: null
      }
    },
    created_at: null,
    updated_at: null,
    steps
  };
}

/** Each write was accepted and sent with the revision the one before returned. */
function expectOneChain(server: ReturnType<typeof makeServer>, from: number): void {
  expect(server.refused).toEqual([]);
  expect(server.sent.map((entry) => entry.expected)).toEqual(
    server.sent.map((_, index) => from + index)
  );
}

const editors: Array<ReturnType<typeof createFlowEditor>> = [];
function editorFor(server: ReturnType<typeof makeServer>, flow: Flow) {
  const editor = createFlowEditor({ flow, eneo: server.eneo });
  editors.push(editor);
  return editor;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  vi.useRealTimers();
});

describe("FlowEditor draft revision", () => {
  it("sends a flow save after a prompt save with the revision the prompt save returned", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4));

    await editor.updateAssistantImmediately("assistant-1", { prompt: { text: "Ny" } });
    editor.setName("Nytt namn");
    await editor.flushFlowSaves();

    expect(server.sent.map((entry) => entry.kind)).toEqual(["assistant", "flow"]);
    expectOneChain(server, 4);
    expect(get(editor.state.resource).draft_revision).toBe(6);
  });

  it("sends a flow save asked for while a prompt save is in flight after it", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4));
    const release = server.hold();

    const prompt = editor.updateAssistantImmediately("assistant-1", { prompt: { text: "Ny" } });
    editor.setName("Nytt namn");
    const flush = editor.flushFlowSaves();
    await vi.advanceTimersByTimeAsync(0);
    // Queued behind the prompt save, not sent alongside it with the same revision.
    expect(server.sent).toHaveLength(1);
    release();
    await Promise.all([prompt, flush]);

    expect(server.sent.map((entry) => entry.kind)).toEqual(["assistant", "flow"]);
    expectOneChain(server, 4);
    expect(get(editor.state.resource).draft_revision).toBe(6);
    expect(get(editor.state.saveStatus)).toBe("saved");
  });

  it("sends a prompt save asked for while a flow autosave is in flight after it", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4));
    const release = server.hold();

    editor.setName("Nytt namn");
    await vi.advanceTimersByTimeAsync(600);
    expect(server.sent).toHaveLength(1);
    const prompt = editor.updateAssistantImmediately("assistant-1", { prompt: { text: "Ny" } });
    await vi.advanceTimersByTimeAsync(0);
    expect(server.sent).toHaveLength(1);
    release();
    await prompt;
    await vi.advanceTimersByTimeAsync(0);

    expect(server.sent.map((entry) => entry.kind)).toEqual(["flow", "assistant"]);
    expectOneChain(server, 4);
    expect(get(editor.state.resource).draft_revision).toBe(6);
    expect(get(editor.state.saveStatus)).toBe("saved");
  });

  it("flushes pending prompts of several assistants one request at a time", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4, [makeStep(1), makeStep(2), makeStep(3)]));
    for (const order of [1, 2, 3]) {
      editor.recordAssistantDraft(`assistant-${order}`, { prompt: { text: `Utkast ${order}` } });
    }

    await editor.flushAssistantSaves();

    expect(server.sent.map((entry) => entry.kind)).toEqual(["assistant", "assistant", "assistant"]);
    expect(server.maxInFlight()).toBe(1);
    expectOneChain(server, 4);
    expect(get(editor.state.resource).draft_revision).toBe(7);
  });

  it("keeps unsaved flow fields when a prompt save advances the revision", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4));
    editor.setName("Osparat namn");

    await editor.updateAssistantImmediately("assistant-1", { prompt: { text: "Ny" } });

    expect(get(editor.state.resource).draft_revision).toBe(5);
    expect(get(editor.state.resource).name).toBe("Flöde");
    expect(get(editor.state.update).name).toBe("Osparat namn");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
    expect(server.sent.map((entry) => entry.kind)).toEqual(["assistant"]);
  });

  it("advances nothing when a prompt save fails", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4));
    editor.setName("Osparat namn");
    vi.mocked(server.eneo.flows.assistants.update).mockRejectedValueOnce(new Error("offline"));

    await expect(
      editor.updateAssistantImmediately("assistant-1", { prompt: { text: "Ny" } })
    ).rejects.toThrow("offline");

    expect(get(editor.state.resource).draft_revision).toBe(4);
    expect(get(editor.state.update).name).toBe("Osparat namn");
    expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);
  });

  it("refuses a prompt save from a tab behind the draft and does not re-base that tab", async () => {
    const server = makeServer(4, { "assistant-1": "Gör uppgift 1." });
    const tabA = editorFor(server, makeFlow(4));
    const tabB = editorFor(server, makeFlow(4));

    tabA.setName("Från flik A");
    await tabA.flushFlowSaves();
    await expect(
      tabB.updateAssistantImmediately("assistant-1", { prompt: { text: "Från flik B" } })
    ).rejects.toMatchObject({ status: 400 });

    // The refused prompt stays in tab B as an unsaved draft, with the reason.
    expect(server.prompts["assistant-1"]).toBe("Gör uppgift 1.");
    expect((await tabB.loadAssistant("assistant-1"))?.prompt?.text).toBe("Från flik B");
    expect(get(tabB.state.validationErrors).get("assistant:assistant-1")).toEqual([
      "Flödet har ändrats sedan det lästes in."
    ]);
    expect(get(tabB.state.resource).draft_revision).toBe(4);

    tabB.setName("Från flik B");
    await expect(tabB.flushFlowSaves()).rejects.toBeInstanceOf(Error);
    expect(server.sent).toEqual([
      { kind: "flow", expected: 4 },
      { kind: "assistant", expected: 4 },
      { kind: "flow", expected: 4 }
    ]);
    expect(server.state.revision).toBe(5);
  });
});

describe("FlowEditor writes that change prompts and steps together", () => {
  it("moves a step, rewriting the prompt that reads it, without refusing its own saves", async () => {
    const server = makeServer(4, {
      "assistant-1": "Gör uppgift 1.",
      "assistant-2": "Gör uppgift 2.",
      "assistant-3": "Läs {{step_2.output.text}}."
    });
    const editor = editorFor(server, makeFlow(4, [makeStep(1), makeStep(2), makeStep(3)]));

    await editor.moveStepAtIndex(1, 1);
    await editor.flushSaves();

    expect(server.prompts["assistant-3"]).toBe("Läs {{step_3.output.text}}.");
    expect(server.sent.map((entry) => entry.kind).sort()).toEqual(["assistant", "flow"]);
    expectOneChain(server, 4);
  });

  it("renames a form field in the prompts that read it without refusing its own saves", async () => {
    const server = makeServer(4, {
      "assistant-1": "Läs {{flow_input.arende}}.",
      "assistant-2": "Sammanfatta {{flow_input.arende}}."
    });
    const editor = editorFor(server, makeFlow(4));
    editor.setName("Namn under tiden");

    await editor.rewriteInputFieldVariableReferences("arende", "arendetext");
    await editor.flushSaves();

    expect(server.sent.filter((entry) => entry.kind === "assistant")).toHaveLength(2);
    expectOneChain(server, 4);
    expect(get(editor.state.resource).name).toBe("Namn under tiden");
  });

  it("renames a step in the prompts of later steps without refusing its own saves", async () => {
    const server = makeServer(4, {
      "assistant-1": "Gör uppgift 1.",
      "assistant-2": "Läs {{ Steg 1 }}."
    });
    const editor = editorFor(server, makeFlow(4));
    editor.setName("Namn under tiden");

    await editor.rewriteStepNameVariableReferences({
      renamedStepOrder: 1,
      oldName: "Steg 1",
      newName: "Underlag"
    });
    await editor.flushSaves();

    expect(server.prompts["assistant-2"]).toBe("Läs {{Underlag}}.");
    expectOneChain(server, 4);
  });

  it("adds a seeded step, saving its prompt and the step without refusing either", async () => {
    const server = makeServer(4);
    const editor = editorFor(server, makeFlow(4, [makeStep(1)]));

    await editor.addStep({ name: "Sammanfatta", prompt: "Sammanfatta kort." });
    await vi.advanceTimersByTimeAsync(600);
    await editor.flushSaves();

    expect(server.prompts["created-Sammanfatta"]).toBe("Sammanfatta kort.");
    expect(server.sent.map((entry) => entry.kind).sort()).toEqual(["assistant", "flow"]);
    expectOneChain(server, 4);
    expect(get(editor.state.saveStatus)).toBe("saved");
  });
});
