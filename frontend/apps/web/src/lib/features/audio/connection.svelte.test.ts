import { describe, expect, it, vi } from "vitest";
import { ConnectionState } from "./connection.svelte";

describe("ConnectionState", () => {
  it("follows the browser's online and offline events and says when it is back", () => {
    const target = new EventTarget();
    const backOnline = vi.fn();
    const connection = new ConnectionState(backOnline, target);

    target.dispatchEvent(new Event("offline"));
    expect(connection.online).toBe(false);
    expect(backOnline).not.toHaveBeenCalled();

    target.dispatchEvent(new Event("online"));
    expect(connection.online).toBe(true);
    expect(backOnline).toHaveBeenCalledOnce();

    connection.dispose();
    target.dispatchEvent(new Event("offline"));
    expect(connection.online).toBe(true);
  });
});
