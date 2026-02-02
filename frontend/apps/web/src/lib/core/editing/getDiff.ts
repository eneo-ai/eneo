/**
 * Options for defining which fields to compare when generating diffs.
 * Supports nested objects and arrays at any depth.
 *
 * Example:
 * ```
 * {
 *   name: true,                   // Compare the whole name field
 *   tools: {                      // Nested object comparison
 *     assistants: ["id"],         // Compare only the id field in each assistant
 *     integrations: ["id", "type"] // Compare id and type fields in each integration
 *   },
 *   members: ["id", "role"]       // Compare only id and role fields in each member
 * }
 * ```
 */
export type CompareOptions<T> = {
  [K in keyof T]?:  // For primitive values or when comparing the whole value
    | true

    // For arrays of objects: specify which fields to compare in each item
    | (T[K] extends Array<infer ArrayItem>
        ? ArrayItem extends Record<string, unknown>
          ? (keyof ArrayItem)[]
          : never
        : never)

    // For nested objects: recursive structure
    | (T[K] extends Record<string, unknown> ? CompareOptions<T[K]> : never);
};

/**
 * Result type for getDiff function.
 * Represents the structure of differences between original and modified objects.
 *
 * The returned diff object will only contain keys that have changes, matching
 * the structure specified in the CompareOptions.
 */
export type Diff<T extends Record<string, unknown>, Compare extends CompareOptions<T>> = {
  [K in keyof Compare]?: K extends keyof T // If key exists in T
    ? // If comparing whole value
      Compare[K] extends true
      ? T[K]
      : // If comparing array items by selected fields
        Compare[K] extends (infer FieldKey)[]
        ? T[K] extends Array<infer Item>
          ? Item extends Record<string, unknown>
            ? { [F in Extract<FieldKey, keyof Item>]: Item[F] }[]
            : T[K]
          : T[K] extends Record<string, unknown>
            ? { [F in Extract<FieldKey, keyof T[K]>]: T[K][F] }
            : T[K]
        : // If recursive comparison of nested object
          Compare[K] extends Record<string, unknown>
          ? T[K] extends Record<string, unknown>
            ? Diff<T[K], Compare[K] & CompareOptions<T[K]>>
            : T[K]
          : // Fallback
            T[K]
    : never;
};

/**
 * Compare the selected fields and keys of two objects based on specified comparison options.
 * Returns an object with only the changed properties, structured for API patch operations.
 *
 * Supports:
 * - Comparing primitive values directly
 * - Comparing entire objects or arrays with all their properties
 * - Comparing only specific fields of objects or arrays of objects
 * - Recursively comparing deeply nested structures
 *
 * @param original The original object to compare from
 * @param copy The modified object to compare against
 * @param options Configuration defining which fields to compare and how
 * @returns An object containing only the changed properties according to the comparison options
 */
export function getDiff<
  T extends Record<string, unknown>,
  K extends T,
  Compare extends CompareOptions<K>
>(
  original: T,
  copy: K,
  options: {
    compare: Compare;
  }
): Diff<K, Compare> {
  const result: Record<string, unknown> = {};

  if (!options?.compare) {
    return {};
  }

  // Iterate through each field specified in the comparison options
  for (const [key, compareValue] of Object.entries(options.compare)) {
    const origValue = original[key];
    const copyValue = copy[key];

    // Case 1: Handle primitive values with direct comparison
    if (isPrimitive(origValue)) {
      if (copyValue !== origValue) {
        result[key] = copyValue;
      }
      continue;
    }

    // Case 1b: Handle null/undefined original values
    // When origValue is null/undefined it is neither primitive nor a record,
    // so subsequent cases that check isRecord(origValue) would all skip it.
    if (origValue === null || origValue === undefined) {
      if (copyValue !== origValue) {
        if (compareValue === true) {
          result[key] = JSON.parse(JSON.stringify(copyValue));
        } else if (isRecord(compareValue) && isRecord(copyValue)) {
          const allFieldsTrue = Object.values(compareValue).every((v) => v === true);
          if (allFieldsTrue) {
            result[key] = extractFields(
              copyValue as Record<string, unknown>,
              Object.keys(compareValue)
            );
          } else {
            const nestedDiff = getDiff(
              {} as Record<string, unknown>,
              copyValue as Record<string, unknown>,
              { compare: compareValue as CompareOptions<Record<string, unknown>> }
            );
            if (Object.keys(nestedDiff).length > 0) {
              result[key] = nestedDiff;
            }
          }
        } else {
          result[key] = copyValue;
        }
      }
      continue;
    }

    // Case 2: Compare entire value (for objects or arrays)
    if (compareValue === true) {
      const originalStr = JSON.stringify(origValue);
      const copyStr = JSON.stringify(copyValue);

      if (originalStr !== copyStr) {
        result[key] = JSON.parse(copyStr);
      }
      continue;
    }

    // Case 3: Handle nested object with recursive comparison
    if (isRecord(compareValue) && isRecord(origValue) && isRecord(copyValue)) {
      // Check if all fields in compareValue are true
      const allFieldsTrue = Object.values(compareValue).every((value) => value === true);

      if (allFieldsTrue) {
        // If all fields are set to true, extract all those fields
        const fields = Object.keys(compareValue);
        const origExtracted = extractFields(origValue, fields);
        const copyExtracted = extractFields(copyValue, fields);

        if (JSON.stringify(origExtracted) !== JSON.stringify(copyExtracted)) {
          result[key] = copyExtracted;
        }
      } else {
        // Recursively generate diff for the nested object
        const nestedDiff = getDiff(
          origValue as Record<string, unknown>,
          copyValue as Record<string, unknown>,
          { compare: compareValue as CompareOptions<Record<string, unknown>> }
        );

        // Only include non-empty diffs in the result
        if (Object.keys(nestedDiff).length > 0) {
          result[key] = nestedDiff;
        }
      }
      continue;
    }

    // Case 4: Object with specific fields comparison
    if (Array.isArray(compareValue) && isRecord(origValue) && isRecord(copyValue)) {
      const fieldsToCompare = compareValue as string[];

      const origExtracted = extractFields(origValue, fieldsToCompare);
      const copyExtracted = extractFields(copyValue, fieldsToCompare);

      if (JSON.stringify(origExtracted) !== JSON.stringify(copyExtracted)) {
        result[key] = copyExtracted;
      }
      continue;
    }

    // Case 5: Array of objects with specific fields comparison
    if (Array.isArray(compareValue) && isArray(origValue) && isArray(copyValue)) {
      const fieldsToCompare = compareValue as string[];

      const origMapped = origValue.map((item) =>
        isRecord(item) ? extractFields(item, fieldsToCompare) : item
      );

      const copyMapped = copyValue.map((item) =>
        isRecord(item) ? extractFields(item, fieldsToCompare) : item
      );

      if (JSON.stringify(origMapped) !== JSON.stringify(copyMapped)) {
        result[key] = copyMapped;
      }
    }
  }

  return result as Diff<K, Compare>;
}

/**
 * Checks if a value is a primitive (string, number, or boolean)
 */
function isPrimitive(value: unknown): value is string | number | boolean {
  return typeof value === "boolean" || typeof value === "string" || typeof value === "number";
}

/**
 * Checks if a value is a non-null, non-array object (a record)
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Checks if a value is a non-null array
 */
function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

/**
 * Extracts specified fields from an object into a new object
 *
 * @param obj The source object to extract fields from
 * @param fields Array of keys to extract
 * @returns A new object containing only the specified fields
 */
function extractFields<T extends Record<string, unknown>>(obj: T, fields: (keyof T)[]) {
  return Object.fromEntries(
    fields
      .filter((field) => field in obj) // Only include fields that exist in the object
      .map((field) => [field, obj[field]])
  );
}
