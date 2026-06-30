import { getAppContext } from "$lib/core/AppContext";
import type { Limits, App } from "@eneo/eneo-js";
import { derived, type Readable } from "svelte/store";
import type { AttachmentRules } from "./AttachmentManager";

type Resource = { completion_model?: { vision: boolean } | null };

/**
 * Get eneo's default attachment limits based on a resource's capabilites,
 * e.g. whether an assistant's completion model supports images/vision.
 *
 * This function returns a store, so it can automatically react to changes in the underlying resource.
 * If you do not need reactivity, you can use the `getAttachmentRules` version instead.
 *
 *  __NOTE__: Can only be called during component initialisation, as it calls into `AppContext`
 */
export function getAttachmentRulesStore(resource: Readable<Resource>) {
  const { limits } = getAppContext();
  return derived(resource, ($resource) => getAttachmentRules({ limits, resource: $resource }));
}

/**
 * Get eneo's default attachment limits based on a resource's capabilites,
 * e.g. whether an assistant's completion model supports images/vision
 */
export function getAttachmentRules(params: {
  limits: Limits;
  resource: Resource;
}): AttachmentRules {
  const { limits, resource } = params;

  const formats = limits.attachments.formats.filter((format) =>
    format.vision ? resource.completion_model?.vision : true
  );

  return {
    maxTotalCount: Infinity,
    acceptedFormats: formats.map(({ mimetype, size }) => {
      return {
        mimetype,
        maxSize: size
      };
    }),
    acceptString: formats.map((f) => f.mimetype).join(",")
  };
}

/**
 * Get the attachment rules based on a specific app's configuration,
 * which is currently determined by it's first configured input field
 *
 * This function returns a store, so it can automatically react to changes in the underlying resource.
 * If you do not need reactivity, you can use the `getAttachmentRules` version instead.
 */
export function getAppAttachmentRulesStore(app: Readable<App>) {
  return derived(app, ($app) => getExplicitAttachmentRules($app.input_fields[0]));
}

/**
 * Get the attachment rules based on a specific app's input field,
 * if none is specified it will just accept anything
 */
export function getExplicitAttachmentRules(rules: {
  accepted_file_types: {
    mimetype: string;
    size_limit: number;
  }[];
  limit: {
    max_files: number;
    max_size: number;
  };
}): AttachmentRules {
  return {
    maxTotalCount: rules?.limit.max_files ?? undefined,
    maxTotalSize: rules?.limit.max_size ?? undefined,
    acceptedFormats:
      rules?.accepted_file_types.map(({ mimetype, size_limit }) => {
        return {
          mimetype,
          maxSize: size_limit
        };
      }) ?? undefined,
    acceptString: rules?.accepted_file_types.map(({ mimetype }) => mimetype).join(",") ?? undefined
  };
}
