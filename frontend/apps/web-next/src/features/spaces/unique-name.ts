import { EneoApiError } from "@/lib/api/errors";

/** Backend ErrorCodes.NAME_COLLISION: the name is taken within the space. */
const NAME_COLLISION = 9017;

/** How many numbered variants to try before giving up ("Ny assistent 20"). */
const MAX_ATTEMPTS = 20;

/**
 * Creates a resource under `name`, and on a name collision retries with a
 * counter ("Ny assistent 2", "Ny assistent 3", …). Any other error, and the
 * last collision, is rethrown so the caller's error handling sees it.
 */
export async function createWithUniqueName<T>(
  name: string,
  create: (name: string) => Promise<T>
): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    const candidate = attempt === 1 ? name : `${name} ${attempt}`;
    try {
      return await create(candidate);
    } catch (error) {
      const collision = error instanceof EneoApiError && error.code === NAME_COLLISION;
      if (!collision || attempt >= MAX_ATTEMPTS) throw error;
    }
  }
}
