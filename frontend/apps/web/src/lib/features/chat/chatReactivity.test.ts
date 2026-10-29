/** Exercise the actual client reactive graph without launching a browser.
 * Server-rendered class tests read getters directly and miss unsubscribed maps.
 */
import { expect, it } from "vitest";
import { build } from "esbuild";
import { compileModule } from "svelte/compiler";
import ts from "typescript";
import { readFile, mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

async function runClientChatCheck(contents: string) {
  const result = await build({
    absWorkingDir: process.cwd(),
    stdin: {
      resolveDir: process.cwd(),
      contents
    },
    bundle: true,
    write: false,
    platform: "node",
    format: "esm",
    conditions: ["browser"],
    plugins: [
      {
        name: "client-runes-without-browser",
        setup(builder) {
          builder.onResolve(
            { filter: /^(\$app\/environment|@eneo\/eneo-js|\$lib\/core\/errors)$/ },
            (args) => ({ path: args.path, namespace: "stub" })
          );
          builder.onLoad({ filter: /.*/, namespace: "stub" }, (args) => ({
            contents:
              args.path === "$app/environment"
                ? "export const browser = false"
                : args.path === "@eneo/eneo-js"
                  ? "export class EneoError extends Error {}"
                  : "export const toastError = () => {}; export const getAnswerFailureMessage = () => undefined"
          }));
          // Let esbuild resolve extensions, including generated Paraglide JavaScript.
          builder.onResolve({ filter: /^\$lib\// }, (args) =>
            builder.resolve(resolve("src/lib", args.path.slice(5)), {
              kind: args.kind,
              resolveDir: args.resolveDir
            })
          );
          builder.onLoad({ filter: /\.svelte\.ts$/ }, async (args) => {
            const source = await readFile(args.path, "utf8");
            const js = ts.transpileModule(source, {
              compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext }
            }).outputText;
            return {
              contents: compileModule(js, { filename: args.path, generate: "client" }).js.code,
              loader: "js"
            };
          });
        }
      }
    ]
  });
  const directory = await mkdtemp(resolve(tmpdir(), "eneo-chat-reactivity-"));
  try {
    const entry = resolve(directory, "check.mjs");
    await writeFile(entry, result.outputFiles[0].text);
    return await promisify(execFile)(process.execPath, [entry], { timeout: 5000 });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

it("updates a subscribed sidebar title and body on argument deltas alone", async () => {
  const { stdout } = await runClientChatCheck(`
      import assert from "node:assert/strict";
      import { ChatService } from "./src/lib/features/chat/ChatService.svelte.ts";
      import { effect_root, render_effect } from "svelte/internal/client";
      import { flushSync } from "svelte";
      let callbacks, finish;
      const chat = new ChatService({
        eneo: { conversations: { ask: async (request) => {
          callbacks = request.callbacks;
          callbacks.onFirstChunk({ id: "message", session_id: "session", answer: "", files: [], generated_files: [], references: [], tools: { assistants: [] } });
          callbacks.onToolCall({ session_id: "session", tools: [{ tool_call_id: "create", server_name: "Documents", tool_name: "create_document", purpose: "file_creation", result_status: "pending" }] });
          await new Promise(resolve => { finish = resolve; });
        } } },
        chatPartner: { id: "assistant", type: "assistant", tools: { assistants: [] } },
        initialConversation: null,
        initialHistory: { items: [], total_count: 0 }
      });
      const pending = chat.askQuestion("Create report");
      let seen;
      const cleanup = effect_root(() => { render_effect(() => { seen = chat.writingDocument; }); });
      flushSync();
      assert.equal(seen.title, "");
      callbacks.onToolCallDelta({ session_id: "session", tool_call_id: "create", arguments_delta: '{"title":"Budget report","content":"First paragraph' });
      flushSync();
      assert.equal(seen.title, "Budget report");
      assert.ok(seen.text.includes("First paragraph"));
      callbacks.onToolCallDelta({ session_id: "session", tool_call_id: "create", arguments_delta: ' continued"}' });
      flushSync();
      assert.ok(seen.text.includes("First paragraph continued"));
      cleanup();
      finish();
      await pending;
      console.log("reactive draft updated");
    `);
  expect(stdout).toContain("reactive draft updated");
}, 20_000);

it("reinitializes only for new page data, without resetting live conversation updates", async () => {
  const { stdout } = await runClientChatCheck(`
    import assert from "node:assert/strict";
    import { ChatService } from "./src/lib/features/chat/ChatService.svelte.ts";
    import { effect_root, render_effect, state, get, set } from "svelte/internal/client";
    import { flushSync } from "svelte";
    const initialConversation = { id: "saved", name: "Saved", messages: [] };
    const data = state({
      eneo: {},
      chatPartner: { id: "assistant", type: "assistant" },
      initialConversation,
      initialHistory: { items: [{ id: "saved", name: "Saved" }], count: 1, total_count: 1 }
    });
    const chat = new ChatService(get(data));
    let initializations = 0;
    const cleanup = effect_root(() => {
      render_effect(() => {
        chat.init(get(data));
        initializations += 1;
      });
    });
    flushSync();
    assert.equal(chat.currentConversation.id, "saved");
    assert.equal(initializations, 1);

    chat.currentConversation = { ...initialConversation, messages: [{ id: "new", question: "Hello", answer: "Hi" }] };
    flushSync();
    assert.equal(chat.currentConversation.messages[0].id, "new");
    assert.equal(initializations, 1);

    set(data, { ...get(data), chatPartner: { id: "other", type: "assistant" }, initialConversation: null, initialHistory: undefined });
    flushSync();
    assert.equal(initializations, 2);
    assert.equal(chat.partner.id, "other");
    assert.equal(chat.currentConversation.id, "");
    assert.equal(chat.loadedConversations.length, 0);
    cleanup();
    console.log("page initialization preserves live chat state");
  `);
  expect(stdout).toContain("page initialization preserves live chat state");
}, 20_000);
