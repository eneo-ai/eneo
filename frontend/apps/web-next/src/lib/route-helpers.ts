import type { QueryClient } from "@tanstack/react-query";
import { notFound, redirect } from "@tanstack/react-router";
import { browserApi } from "./api/browser";
import { EneoApiError } from "./api/errors";
import { readCached } from "./api/query";
import { sessionQueries } from "./api/session";
import { hasPermission, type PermissionRequirement } from "./auth/permissions";

/** Only a missing resource becomes not-found; refusals and other errors keep their owner. */
export async function notFoundOn404<T>(read: Promise<T>): Promise<T> {
  try {
    return await read;
  } catch (error) {
    if (error instanceof EneoApiError && error.status === 404) throw notFound();
    throw error;
  }
}

/** Read-only UX guard. The app gate owns the session; the backend owns authorization. */
export async function requirePermission(
  { queryClient }: { queryClient: QueryClient },
  permission: PermissionRequirement,
  to: string
): Promise<void> {
  const user = await readCached(queryClient, sessionQueries(browserApi).me);
  if (!hasPermission(user)(permission)) throw redirect({ href: to, replace: true });
}

// Entity editors must use the router's remountDeps on their entity ID, for
// example remountDeps: ({ params }) => params.assistantId. This flushes a dirty
// autosave draft through its original entity's save before the next editor
// mounts. Search/tab changes must not remount it or discard its draft.
