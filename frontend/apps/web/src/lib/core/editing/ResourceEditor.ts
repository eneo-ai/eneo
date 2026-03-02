import { IntricError, type Intric, type UploadedFile } from "@intric/intric-js";
import { toast } from "$lib/components/toast";
import { derived, get, readonly, writable } from "svelte/store";
import { getAddedItems, getRemovedItems } from "./getChangedItems";
import { getDiff, type CompareOptions, type Diff } from "./getDiff";
import { applyDefaults, type AppliedDefaults, type Defaults } from "./applyDefaults";

type Resource = Record<string, unknown> & { id: string };

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
    resource: { id: string },
    changes:
      | Diff<AppliedDefaults<T, Defs>, CompareOptions<AppliedDefaults<T, Defs>>>
      | { [key in keyof T]: T[key] }
  ) => Promise<T>;
  /** Provide a key if attachements should also be managed, e.g. deleted when the attachment field is reverted */
  manageAttachements: Extract<keyof T, string> | false;
  intric: Intric;
}) {
  const { intric, updateResource } = data;
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

  /** Will save the current changes to this resource and delete removed files */
  async function saveChanges(field: keyof T | undefined = undefined) {
    try {
      // Get changes to this resource
      const $resource = get(resource);
      const $update = get(update);
      isSaving.set(true);
      const changes = field
        ? ({ [field]: $update[field] } as unknown as { [key in keyof T]: T[key] })
        : get(currentChanges).diff;
      // Check if some files have been removed
      // We could also directly remove files from the backend when the remove file button in the ui is clicked,
      // however this would be an irreversible change. If we delay the deletion until we save the resource,
      // we can actually cancel all changes anytime before they have been comitted.

      const removedFiles = getRemovedAttachments($resource, $update, data.manageAttachements);

      // ... run update code here
      // We can call const update = normalisedCopy(changes), so we send only id fields once API is up
      const updated = applyDefaults(await updateResource($resource, changes), data.defaults);
      resource.set(updated);

      // Now we need to apply the changes to the update (which could have been partial changes)
      // So we cant just use the actual updated resource, as we want to even keep unsaved changes
      update.set(applyUpdates<AppliedDefaults<T, Defs>>($update, updated, field));

      // Service has been updated successfully, now we can safely delete files if we need to
      // which is the case if either everything was saved, or the files field was saved
      if (field === undefined || field === "files") {
        removedFiles.forEach((file) => {
          try {
            intric.files.delete({ fileId: file.id });
          } catch {
            console.error(`Couldnt delete removed file ${file.id}`);
          }
        });
      }
    } catch (e) {
      const message = e instanceof IntricError ? e.getReadableMessage() : "Error while trying to update";
      toast.error(message);
      console.error(message);
    }
    isSaving.set(false);
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
            intric.files.delete({ fileId: upload.id });
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

function applyUpdates<T extends Record<string, unknown>>(
  input: T,
  update: T,
  field: keyof T | undefined
) {
  const updateCopy = JSON.parse(JSON.stringify(update));

  if (field === undefined) {
    // If everything was saved we return everything
    return updateCopy;
  }

  const base = JSON.parse(JSON.stringify(input));
  base[field] = updateCopy[field];

  return base as T;
}
