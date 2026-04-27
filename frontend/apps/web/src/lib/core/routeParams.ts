import { error } from "@sveltejs/kit";

const UUID_PARAM_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function requireUuidRouteParam(value: string | undefined, name: string): string {
  if (!value || value === "undefined" || !UUID_PARAM_PATTERN.test(value)) {
    throw error(404, {
      message: `${name} was not found.`,
      status: 404,
      code: 0
    });
  }

  return value;
}
