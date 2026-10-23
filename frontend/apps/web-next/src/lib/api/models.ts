import type { components } from "./schema";

/** Shorthand for backend model types: `Schema<"SpacePublic">`. */
export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];
