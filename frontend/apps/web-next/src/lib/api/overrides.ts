/**
 * Hand-written corrections for places where the backend OpenAPI spec
 * under-specifies a response shape (the generated schema.d.ts says `unknown`
 * or is wider than the actual payload).
 *
 * Rules:
 *  - Every override documents WHAT the spec gets wrong and is an RB-5
 *    candidate: the real fix is the backend response model, not this file.
 *  - Keep overrides minimal and per-type; never fork whole endpoint trees
 *    (the old intric-js resources.d.ts is the cautionary tale).
 *
 * No overrides yet.
 */

export {};
