// A Web Locks stand-in for tests: exclusive locks by name, `ifAvailable` answered with null
// while the name is held.

type Callback = (lock: { name: string } | null) => Promise<unknown>;

export function fakeLocks() {
  const held = new Map<string, Promise<void>>();
  const manager = {
    held,
    async request(name: string, options: { ifAvailable?: boolean } | Callback, maybe?: Callback) {
      const callback = typeof options === "function" ? options : maybe!;
      if (typeof options !== "function" && options.ifAvailable && held.has(name)) {
        return callback(null);
      }
      while (held.has(name)) await held.get(name);
      let free = () => {};
      held.set(name, new Promise<void>((resolve) => (free = resolve)));
      try {
        return await callback({ name });
      } finally {
        held.delete(name);
        free();
      }
    }
  };
  return manager as typeof manager & LockManager;
}
