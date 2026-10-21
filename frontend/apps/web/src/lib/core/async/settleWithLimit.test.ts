import { describe, expect, it } from "vitest";
import { settleWithLimit } from "./settleWithLimit";

describe("settleWithLimit", () => {
  it("keeps at most the limit in flight and the results in order", async () => {
    let inFlight = 0;
    let most = 0;
    const results = await settleWithLimit([1, 2, 3, 4, 5, 6, 7], 3, async (value) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 8 - value));
      inFlight -= 1;
      if (value === 4) throw new Error("four");
      return value * 10;
    });

    expect(most).toBe(3);
    expect(results.map((result) => (result.status === "fulfilled" ? result.value : "x"))).toEqual([
      10,
      20,
      30,
      "x",
      50,
      60,
      70
    ]);
  });

  it("settles nothing for no items", async () => {
    expect(await settleWithLimit([], 4, async () => 1)).toEqual([]);
  });
});
