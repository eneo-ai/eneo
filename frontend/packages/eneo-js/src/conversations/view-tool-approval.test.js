import assert from "node:assert/strict";
import test from "node:test";
import { EneoError } from "../client/client.js";
import { runViewToolWithApproval } from "./view-tool-approval.js";

test("a stale automatic call requests fresh consent before invoking the tool again", async () => {
  const events = [];
  const result = await runViewToolWithApproval({
    automaticRevision: 7,
    invoke: async (revision) => {
      events.push(["invoke", revision]);
      if (revision !== undefined) throw new EneoError("Changed", "RESPONSE", 409, 9065);
      return "answer";
    },
    confirm: async () => {
      events.push(["confirm"]);
      return true;
    }
  });
  assert.equal(result, "answer");
  assert.deepEqual(events, [["invoke", 7], ["confirm"], ["invoke", undefined]]);
});

test("a view in a conversation with no saved revision asks before making any call", async () => {
  let asked = false;
  await assert.rejects(
    runViewToolWithApproval({
      automaticRevision: 0,
      invoke: async () => assert.fail("An unconfirmed tool should never have run"),
      confirm: async () => {
        asked = true;
        return false;
      }
    }),
    /did not allow/
  );
  assert.equal(asked, true);
});

test("an automatic call with an uncertain outcome is never replayed", async () => {
  for (const [status, code] of [
    [503, 0],
    [409, 0]
  ]) {
    const failure = Object.assign(new Error("Call failed"), { status, code });
    let attempts = 0;
    await assert.rejects(
      runViewToolWithApproval({
        automaticRevision: 12,
        invoke: async () => {
          attempts++;
          throw failure;
        },
        confirm: async () => assert.fail("A failed call cannot be retried as a new confirmed call")
      }),
      (error) => error === failure
    );
    assert.equal(attempts, 1);
  }
});
