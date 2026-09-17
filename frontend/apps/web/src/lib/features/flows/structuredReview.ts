export type ReviewValue =
  string | number | boolean | null | ReviewValue[] | { [key: string]: ReviewValue };

export type ReviewSchema = Record<string, unknown>;

function isReviewSchema(value: unknown): value is ReviewSchema {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function reviewSchema(value: unknown): ReviewSchema {
  return isReviewSchema(value) ? value : {};
}

export function isReviewObject(
  value: ReviewValue | undefined
): value is { [key: string]: ReviewValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isReviewValue(value: unknown, depth = 0): value is ReviewValue {
  if (depth > 100) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => isReviewValue(item, depth + 1));
  return (
    value !== null &&
    typeof value === "object" &&
    Object.values(value).every((item) => isReviewValue(item, depth + 1))
  );
}

export function parseReviewValue(text: string): ReviewValue | undefined {
  try {
    const value: unknown = JSON.parse(text);
    return isReviewValue(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

export function reviewFieldKind(schema: ReviewSchema, value?: ReviewValue) {
  // The server validates the full contract. Do not guess a branch or resolve references here.
  if (["$ref", "allOf", "anyOf", "oneOf", "if", "not"].some((key) => key in schema))
    return "unsupported";
  if ("const" in schema || schema.readOnly === true) return "readonly";
  // Keep incompatible stored values visible instead of replacing them with blank controls.
  if (value !== undefined) {
    switch (schema.type) {
      case "object":
        if (!isReviewObject(value)) return "unsupported";
        break;
      case "array":
        if (!Array.isArray(value)) return "unsupported";
        break;
      case "string":
        if (typeof value !== "string") return "unsupported";
        break;
      case "number":
      case "integer":
        if (typeof value !== "number" && value !== "") return "unsupported";
        break;
      case "boolean":
        if (typeof value !== "boolean" && value !== "") return "unsupported";
        break;
    }
  }
  if (Array.isArray(schema.enum) && schema.enum.every((value) => typeof value === "string"))
    return "enum";
  switch (schema.type) {
    case "object":
      return schema.properties &&
        typeof schema.properties === "object" &&
        !Array.isArray(schema.properties)
        ? "object"
        : "unsupported";
    case "array":
      return schema.items && typeof schema.items === "object" && !Array.isArray(schema.items)
        ? "array"
        : "unsupported";
    case "string":
      return "string";
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return "boolean";
    default:
      return "unsupported";
  }
}

export function reviewFieldLabel(schema: ReviewSchema, key: string): string {
  if (typeof schema.title === "string" && schema.title.trim()) return schema.title;
  return key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function reviewObjectFields(schema: ReviewSchema, value: ReviewValue | undefined) {
  const properties = reviewSchema(schema.properties);
  const keys = new Set([
    ...Object.keys(properties),
    ...Object.keys(isReviewObject(value) ? value : {})
  ]);
  return [...keys].map((key) => ({ key, schema: reviewSchema(properties[key]) }));
}

export function reviewItemPreview(schema: ReviewSchema, value: ReviewValue): string {
  if (!isReviewObject(value)) return "";
  const preview = reviewObjectFields(schema, value)
    .filter((field) => reviewFieldKind(field.schema) === "string")
    .map((field) => value[field.key])
    .filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    .slice(0, 2)
    .join(": ");
  return preview.length > 140 ? `${preview.slice(0, 140)}…` : preview;
}

export function replaceReviewProperty(
  value: ReviewValue | undefined,
  key: string,
  next: ReviewValue
): ReviewValue {
  // Retain fields absent from the snapshot schema, including extension data.
  return { ...(isReviewObject(value) ? value : {}), [key]: next };
}

export function emptyReviewValue(schema: ReviewSchema, depth = 0): ReviewValue {
  if (depth > 20) return null;
  if ("const" in schema && isReviewValue(schema.const)) return schema.const;
  if (schema.type === "object") {
    return Object.fromEntries(
      Object.entries(reviewSchema(schema.properties))
        .filter(([key]) => Array.isArray(schema.required) && schema.required.includes(key))
        .map(([key, child]) => [key, emptyReviewValue(reviewSchema(child), depth + 1)])
    );
  }
  if (schema.type === "array") return [];
  // A new row has no inferred enum choice, quantity, boolean, name or date.
  return "";
}
