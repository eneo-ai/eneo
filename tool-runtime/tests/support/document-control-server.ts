// Real shared engines; subprocess confinement has its own runtime tests.
import { createHandler } from "../../src/server";
import { documentControlRenderer } from "../../src/tools/documents/control";
import { fileRenderer, fileInspector } from "../../src/tools/documents/tool";
import { executeRender, executeInspect } from "../../src/tools/documents/execute";
const server = Bun.serve({
  hostname: "127.0.0.1",
  port: 0,
  fetch: createHandler({
    token: process.env.TEST_DOCUMENT_TOKEN!,
    maxConcurrency: 2,
    endpoints: [],
    renderDocument: documentControlRenderer(fileRenderer(executeRender), 10 * 1024 * 1024),
    inspectTemplate: fileInspector(executeInspect),
  }),
});
console.log(server.port);
