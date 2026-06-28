/**
 * Creates a version of an asynchronous function that provides an `isLoading` $state on the function.
 * Will not catch any errors, you should handle errors inside your async function.
 *
 * @example
 * const loadUsers = createAsyncState(async () => {
 *   return await eneo.users.list();
 * });
 *
 * // True while is loading
 * loadUsers.isLoading
 */
export function createAsyncState<Args extends unknown[], Return>(fn: AsyncFunction<Args, Return>) {
  let _isLoading = $state(false);

  async function apply(...args: Args) {
    _isLoading = true;
    try {
      const res = await fn(...args);
      return res;
    } finally {
      _isLoading = false;
    }
  }

  Object.defineProperty(apply, "isLoading", {
    configurable: false,
    enumerable: true,
    get() {
      return _isLoading;
    }
  });

  return apply as typeof apply & { isLoading: boolean };
}

type AsyncFunction<Args extends unknown[], Return> = (...args: Args) => Promise<Return>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AsyncState<F extends (...args: any[]) => Promise<any>> = F & {
  isLoading: boolean;
};
