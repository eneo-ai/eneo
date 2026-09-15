import { type Eneo, type UploadedFile } from "@eneo/eneo-js";
import { derived, get, readonly, writable } from "svelte/store";
import { getAddedItems, getRemovedItems } from "./getChangedItems";
import { getDiff, type CompareOptions, type Diff } from "./getDiff";
import { applyDefaults, type AppliedDefaults, type Defaults } from "./applyDefaults";
import { toastError } from "$lib/core/errors";

type Resource = Record<string, unknown> & { id: string };

/**
 * Per-invocation outcome of saveChanges. `handled` is true when onSaveError
 * owned the failure (e.g. routed it into a validation banner), so the caller
 * can classify this exact request without shared mutable state.
 */
export type ResourceSaveResult =
  | { saved: true }
  | { saved: false; error: unknown; handled: boolean }
  /** `canSave` refused the state when the queued save ran; nothing was sent. */
  | { saved: false; deferred: true };

/**
 * Create a resource editor for the specified resource. It will create stores for the original data,
 * a bindable updatable value, and an automatically generated diff that can be sent to the PATCH endpoints
 * to save the resource.
 */
export function createResourceEditor<T extends Resource, Defs extends Defaults<T>>(data: {
  resource: T;
  /** Define some defaults that will overwrite fields that are not set */
  defaults: Defs;
  /** Decide which fields the diff should be generated for and what sub-fields to include
   * Useful to e.g. only keep track of the ID of completion models instead of the whole object
   */
  editableFields: CompareOptions<AppliedDefaults<T, Defs>>;
  /** Specify a function to run when the updates are saved, this is usually the specific PATCH endpoint for the resource */
  updateResource: (
    resource: AppliedDefaults<T, Defs>,
    changes:
      | Diff<AppliedDefaults<T, Defs>, CompareOptions<AppliedDefaults<T, Defs>>>
      | { [key in keyof T]: T[key] }
  ) => Promise<T>;
  /** Provide a key if attachements should also be managed, e.g. deleted when the attachment field is reverted */
  manageAttachements: Extract<keyof T, string> | false;
  /**
   * Owns a failed save before the default toast fires. Return true when the
   * error was surfaced elsewhere (e.g. a validation banner) to suppress the
   * raw-message toast; the save still resolves unsaved, carrying the error
   * and this handled flag in its result.
   */
  onSaveError?: (error: unknown) => boolean;
  /**
   * Decides, when a queued save actually runs, whether the current state may
   * be persisted. Validation done when the save was queued can be stale by
   * the time an earlier save lets it run; a false answer defers the save and
   * keeps the state dirty instead of sending what the endpoint would reject.
   */
  canSave?: (update: AppliedDefaults<T, Defs>) => boolean;
  /**
   * Called for a field the user edited WHILE a save of it was in flight. The
   * local value wins (it is newer than the response), but the server may have
   * assigned identities the local copy lacks (e.g. ids for created items);
   * return the local value with those folded in. Default: the local value as is.
   */
  mergeUnsavedField?: (
    field: keyof AppliedDefaults<T, Defs>,
    local: unknown,
    saved: unknown
  ) => unknown;
  eneo: Eneo;
}) {
  const { eneo, updateResource } = data;
  // To be able to edit the resource we need to deep clone the input,
  //  otherwise we bind to pointers and change everything at the same time

  const serialisedService = JSON.stringify(applyDefaults(data.resource, data.defaults));
  const resource = writable<AppliedDefaults<T, Defs>>(JSON.parse(serialisedService));
  const update = writable<AppliedDefaults<T, Defs>>(JSON.parse(serialisedService));
  const currentChanges = derived(update, ($update) => {
    const diff = getDiff(get(resource), $update, {
      compare: data.editableFields
    });
    return {
      diff,
      hasUnsavedChanges: Object.keys(diff).length > 0
    };
  });
  const isSaving = writable(false);

  // Saves run one at a time. A save requested while another is in flight
  // waits for it and then sends whatever is still unsaved. Two overlapping
  // requests would carry overlapping state, and the later one would be
  // fenced on a revision the earlier one already advanced: the user then
  // sees a "changed elsewhere" conflict caused by their own click.
  let saveChain: Promise<unknown> = Promise.resolve();
  let savesPending = 0;

  /** Resolves once every save queued so far has settled (saved, failed or
   *  deferred). The dirty state is only meaningful after that. */
  function settled(): Promise<void> {
    return saveChain.then(() => undefined);
  }

  /** Will save the current changes to this resource and delete removed files */
  function saveChanges(field: keyof T | undefined = undefined): Promise<ResourceSaveResult> {
    savesPending += 1;
    isSaving.set(true);
    const run = saveChain.then(() => runSave(field));
    saveChain = run.catch(() => undefined);
    return run;
  }

  async function runSave(field: keyof T | undefined): Promise<ResourceSaveResult> {
    try {
      // Get changes to this resource
      const $resource = get(resource);
      const $update = get(update);
      if (data.canSave && !data.canSave($update)) {
        return { saved: false, deferred: true };
      }
      // Bound inputs edit the store's object in place, so the comparison
      // after the response needs a copy of what was sent, not a reference.
      const snapshot: typeof $update = JSON.parse(JSON.stringify($update));
      const changes = field
        ? ({ [field]: $update[field] } as unknown as { [key in keyof T]: T[key] })
        : get(currentChanges).diff;
      // A queued save whose changes an earlier save already carried has
      // nothing to send.
      if (field === undefined && Object.keys(changes).length === 0) {
        return { saved: true };
      }
      // Check if some files have been removed
      // We could also directly remove files from the backend when the remove file button in the ui is clicked,
      // however this would be an irreversible change. If we delay the deletion until we save the resource,
      // we can actually cancel all changes anytime before they have been comitted.

      const removedFiles = getRemovedAttachments($resource, $update, data.manageAttachements);

      // ... run update code here
      // We can call const update = normalisedCopy(changes), so we send only id fields once API is up
      const updated = applyDefaults(await updateResource($resource, changes), data.defaults);
      resource.set(updated);

      // The response describes the state as of the snapshot that was sent.
      // Anything the user changed since then is newer than the response and
      // stays local (it goes in the next save); everything else takes the
      // server's copy, which may carry normalised values and assigned ids.
      update.set(
        mergeSavedState<AppliedDefaults<T, Defs>>({
          snapshot,
          current: get(update),
          saved: updated,
          field,
          mergeUnsavedField: data.mergeUnsavedField
        })
      );

      // Service has been updated successfully, now we can safely delete files if we need to
      // which is the case if either everything was saved, or the files field was saved
      if (field === undefined || field === "files") {
        removedFiles.forEach((file) => {
          try {
            eneo.files.delete({ fileId: file.id });
          } catch {
            console.error(`Couldnt delete removed file ${file.id}`);
          }
        });
      }
      return { saved: true };
    } catch (e) {
      const handled = data.onSaveError?.(e) === true;
      if (!handled) {
        toastError(e);
      }
      return { saved: false, error: e, handled };
    } finally {
      savesPending -= 1;
      if (savesPending === 0) isSaving.set(false);
    }
  }

  function discardChanges(field: keyof T | undefined = undefined) {
    update.update(($update) => {
      const $resource = get(resource);
      // Check if files have been uploaded that should be reverted

      const discardedUploads = getAddedAttachments($resource, $update, data.manageAttachements);

      if (field) {
        $update[field] = $resource[field];
      } else {
        $update = $resource;
      }

      // Delete uploaded files either if resetting everything or field `files`
      if (field === undefined || field === "attachments") {
        discardedUploads.forEach((upload) => {
          try {
            eneo.files.delete({ fileId: upload.id });
          } catch {
            console.error(`Couldn't delete existing upload ${upload.id}`);
          }
        });
      }

      return JSON.parse(JSON.stringify($update));
    });
  }

  /** Replace both persisted and editable state (e.g. after publish/unpublish) */
  function setResource(value: T) {
    const applied = applyDefaults(value, data.defaults);
    resource.set(applied);
    update.set(JSON.parse(JSON.stringify(applied)));
  }

  return Object.freeze({
    state: {
      /** Read-only, current persisted state of the resource */
      resource: readonly(resource),
      /** Bindable, an update that should be sent to the resource */
      update,
      /** Read-only, current difference between persisted an UI state */
      currentChanges,
      /** Read-only, If the resource is currently being saved */
      isSaving: readonly(isSaving)
    },
    saveChanges,
    settled,
    discardChanges,
    setResource
  });
}

function getAddedAttachments(
  base: Record<string, unknown>,
  update: Record<string, unknown>,
  key: string | false
) {
  if (!key) return [];
  return hasAttachments(base, key) && hasAttachments(update, key)
    ? getAddedItems(base[key], update[key])
    : [];
}

function getRemovedAttachments(
  base: Record<string, unknown>,
  update: Record<string, unknown>,
  key: string | false
) {
  if (!key) return [];
  return hasAttachments(base, key) && hasAttachments(update, key)
    ? getRemovedItems(base[key], update[key])
    : [];
}

function hasAttachments(
  value: Record<string, unknown>,
  key: string
): value is { [x in typeof key]: UploadedFile[] } {
  return typeof value === "object" && value !== null && key in value && Array.isArray(value[key]);
}

function mergeSavedState<T extends Record<string, unknown>>(args: {
  /** The editable state at the moment the save was sent. */
  snapshot: T;
  /** The editable state now, after the response arrived. */
  current: T;
  /** The resource as the server returned it. */
  saved: T;
  field: keyof T | undefined;
  mergeUnsavedField?: (field: keyof T, local: unknown, saved: unknown) => unknown;
}): T {
  const { snapshot, current, saved, field, mergeUnsavedField } = args;
  const savedCopy: T = JSON.parse(JSON.stringify(saved));
  const result: T = JSON.parse(JSON.stringify(current));
  const keys = (field === undefined ? Object.keys(savedCopy) : [field]) as (keyof T)[];
  for (const key of keys) {
    const editedDuringSave =
      JSON.stringify(current[key] ?? null) !== JSON.stringify(snapshot[key] ?? null);
    result[key] = editedDuringSave
      ? ((mergeUnsavedField?.(key, current[key], savedCopy[key]) ?? current[key]) as T[keyof T])
      : savedCopy[key];
  }
  return result;
}
