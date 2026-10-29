import assert from "node:assert/strict";
import test from "node:test";
import { createWidgetClient } from "../widget.js";

for (const injectedFetch of [true, false]) {
  test(`widget requests omit cookies with ${injectedFetch ? "injected" : "native"} fetch`, async (t) => {
    const requests = [];
    let minted = 0;
    const transport = async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      const path = new URL(request.url).pathname;
      if (path.endsWith("/ask/")) {
        return new Response(
          'event: first_chunk\ndata: {"session_id":"s","answer":""}\n\n' +
            'event: text\ndata: {"session_id":"s","answer":"Hello","references":[]}\n\n',
          { headers: { "Content-Type": "text/event-stream" } }
        );
      }
      if (path.endsWith("/visitor-sessions/")) {
        return Response.json({ token: `visitor-${++minted}`, expires_in: 3600 });
      }
      if (path.endsWith("/config/")) return Response.json({ public_id: "wgt_x" });
      if (path.endsWith("/feedback/")) return Response.json({ value: 1 });
      return Response.json({ id: "s" });
    };
    if (!injectedFetch) t.mock.method(globalThis, "fetch", transport);
    let token = null;
    const widget = createWidgetClient({
      baseUrl: "https://eneo.example",
      publicId: "wgt_x",
      getToken: () => token,
      ...(injectedFetch ? { fetch: transport } : {})
    });

    assert.equal((await widget.config()).public_id, "wgt_x");
    token = (await widget.createVisitorSession({ altcha: "solved-challenge" })).token;
    assert.equal((await widget.conversations.get({ id: "s" })).id, "s");
    const controller = new AbortController();
    assert.equal(
      (await widget.conversations.ask({ question: "Hello", abortController: controller })).answer,
      "Hello"
    );
    await widget.conversations.leaveFeedback({ conversation: { id: "s" }, feedback: { value: 1 } });
    token = (await widget.createVisitorSession({ previousToken: token })).token;
    assert.equal(
      (await widget.conversations.ask({ conversation: { id: "s" }, question: "Again" })).answer,
      "Hello"
    );

    assert.deepEqual(
      requests.map((request) => [request.method, new URL(request.url).pathname]),
      [
        ["GET", "/api/v1/widgets/wgt_x/config/"],
        ["POST", "/api/v1/widgets/wgt_x/visitor-sessions/"],
        ["GET", "/api/v1/widgets/wgt_x/sessions/s/"],
        ["POST", "/api/v1/widgets/wgt_x/ask/"],
        ["POST", "/api/v1/widgets/wgt_x/sessions/s/feedback/"],
        ["POST", "/api/v1/widgets/wgt_x/visitor-sessions/"],
        ["POST", "/api/v1/widgets/wgt_x/ask/"]
      ]
    );
    for (const request of requests) assert.equal(request.credentials, "omit", request.url);
    assert.deepEqual(
      requests.map((request) => request.headers.get("Authorization")),
      [
        null,
        null,
        "Bearer visitor-1",
        "Bearer visitor-1",
        "Bearer visitor-1",
        "Bearer visitor-1",
        "Bearer visitor-2"
      ]
    );
    assert.equal((await requests[1].json()).altcha, "solved-challenge");
    assert.equal((await requests[5].json()).previous_token, "visitor-1");
    assert.deepEqual(await requests[6].json(), { question: "Again", session_id: "s" });
    controller.abort();
    assert.equal(requests[3].signal.aborted, true);

    token = null;
    await widget.config();
    assert.equal(requests.at(-1).headers.get("Authorization"), null);
    assert.equal(requests.at(-1).credentials, "omit");
  });
}

test("draft preview configuration uses its bearer token without cookies", async () => {
  const widget = createWidgetClient({
    baseUrl: "https://eneo.example",
    publicId: "wgt_draft",
    getToken: () => "preview-token",
    fetch: async (input, init) => {
      const request = new Request(input, { ...init, cache: "no-store" });
      assert.equal(request.credentials, "omit");
      assert.equal(request.headers.get("Authorization"), "Bearer preview-token");
      assert.equal(request.cache, "no-store");
      return Response.json({ public_id: "wgt_draft" });
    }
  });
  assert.equal((await widget.config()).public_id, "wgt_draft");
});
