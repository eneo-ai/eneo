import { describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { createWithUniqueName } from "./unique-name";

const collision = () => new EneoApiError("Name collision", { status: 400, code: 9017 });

describe("createWithUniqueName", () => {
  it("creates under the name itself when it is free", async () => {
    const create = vi.fn((name: string) => Promise.resolve({ name }));
    await expect(createWithUniqueName("Ny assistent", create)).resolves.toEqual({
      name: "Ny assistent"
    });
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("numbers the name on a collision until one is free", async () => {
    const create = vi
      .fn<(name: string) => Promise<{ name: string }>>()
      .mockRejectedValueOnce(collision())
      .mockRejectedValueOnce(collision())
      .mockImplementation((name) => Promise.resolve({ name }));
    await expect(createWithUniqueName("Ny assistent", create)).resolves.toEqual({
      name: "Ny assistent 3"
    });
    expect(create.mock.calls.map(([name]) => name)).toEqual([
      "Ny assistent",
      "Ny assistent 2",
      "Ny assistent 3"
    ]);
  });

  it("rethrows any other error at once", async () => {
    const error = new EneoApiError("Forbidden", { status: 403, code: 9001 });
    const create = vi.fn(() => Promise.reject(error));
    await expect(createWithUniqueName("Ny app", create)).rejects.toBe(error);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("gives up after the twentieth variant", async () => {
    const create = vi.fn(() => Promise.reject(collision()));
    await expect(createWithUniqueName("Ny gruppchatt", create)).rejects.toBeInstanceOf(
      EneoApiError
    );
    expect(create).toHaveBeenCalledTimes(20);
  });
});
