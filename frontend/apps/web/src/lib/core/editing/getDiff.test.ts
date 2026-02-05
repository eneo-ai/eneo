import { expect, test } from "vitest";
import { getDiff } from "./getDiff";

test("Detect change in selected prop", () => {
  const a = { id: "1", name: "group1" };
  const b = { id: "1", name: "group2" };

  expect(getDiff(a, b, { compare: { name: true } })).toEqual({ name: "group2" });
});

test("Detect change in child object when comparing all props", () => {
  const a = { id: "1", person: { name: "test", age: 20 } };
  const b = { id: "1", person: { name: "test", age: 30 } };

  expect(getDiff(a, b, { compare: { person: true } })).toEqual({
    person: { name: "test", age: 30 }
  });
});

test("Detect no change in child object when comparing all props", () => {
  const a = { id: "1", person: { name: "test", age: 20 } };
  const b = { id: "1", person: { name: "test", age: 20 } };

  expect(getDiff(a, b, { compare: { person: true } })).toEqual({});
});

test("Detect change in child object when comparing specific prop", () => {
  const a = { id: "1", person: { name: "test", age: 20 } };
  const b = { id: "1", person: { name: "test", age: 30 } };

  expect(getDiff(a, b, { compare: { person: { age: true } } })).toEqual({
    person: { age: 30 }
  });
});

test("Detect change in child object when comparing specific prop, include all specified props", () => {
  const a = { id: "1", person: { name: "test", age: 20 } };
  const b = { id: "1", person: { name: "test", age: 30 } };

  expect(getDiff(a, b, { compare: { person: { name: true, age: true } } })).toEqual({
    person: { name: "test", age: 30 }
  });
});

test("Detect combined diff", () => {
  const a = { id: "1", name: "group1", metadata: { title: "link" } };
  const b = { id: "1", name: "group2", metadata: { title: "external" } };
  expect(
    getDiff(a, b, {
      compare: {
        name: true,
        metadata: true
      }
    })
  ).toEqual({ name: "group2", metadata: { title: "external" } });
});

test("Detect array diff", () => {
  const a = { id: "1", groups: [1, 2, 3] };
  const b = { id: "1", groups: [1, 2] };
  expect(getDiff(a, b, { compare: { groups: true } })).toEqual({ groups: [1, 2] });
});

test("Detect deep array diff on full compare", () => {
  const a = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "2", age: 20 }
    ]
  };
  const b = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "4", age: 30 }
    ]
  };
  expect(getDiff(a, b, { compare: { groups: true } })).toEqual({
    groups: [
      { name: "1", age: 20 },
      { name: "4", age: 30 }
    ]
  });
});

test("Detect deep array diff on specific compare", () => {
  const a = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "2", age: 20 }
    ]
  };
  const b = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "4", age: 30 }
    ]
  };
  expect(getDiff(a, b, { compare: { groups: ["age"] } })).toEqual({
    groups: [{ age: 20 }, { age: 30 }]
  });
});

test("Detect deep array diff on specific compare, include all compared fields", () => {
  const a = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "2", age: 20 }
    ]
  };
  const b = {
    id: "1",
    groups: [
      { name: "1", age: 20 },
      { name: "4", age: 30 }
    ]
  };
  expect(getDiff(a, b, { compare: { groups: ["age", "name"] } })).toEqual({
    groups: [
      { name: "1", age: 20 },
      { name: "4", age: 30 }
    ]
  });
});

test("Detect added prop", () => {
  const a = { id: "1" };
  const b = { id: "1", name: "group2" };
  expect(getDiff(a, b, { compare: { name: true } })).toEqual({ name: "group2" });
});

test("Empty comparison returns empty object", () => {
  const a = { id: "1" };
  const b = { id: "1", name: "group2" };
  expect(getDiff(a, b, { compare: {} })).toEqual({});
});

test("Detect nested object diff with nested arrays", () => {
  const original = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [
        { id: "asst1", name: "Assistant 1" },
        { id: "asst2", name: "Assistant 2" }
      ]
    }
  };

  const modified = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [
        { id: "asst1", name: "Assistant 1" },
        { id: "asst3", name: "Assistant 3" }
      ]
    }
  };

  // Compare with nested fields configuration
  const diff = getDiff(original, modified, {
    compare: {
      tools: {
        assistants: ["id"]
      }
    }
  });

  // Expected: only the IDs in the assistants array should be compared
  expect(diff).toEqual({
    tools: {
      assistants: [{ id: "asst1" }, { id: "asst3" }]
    }
  });
});

test("Omit nested property when no changes", () => {
  const original = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [
        { id: "asst1", name: "Assistant 1" },
        { id: "asst2", name: "Assistant 2" }
      ],
      integrations: [{ id: "int1", name: "Integration 1" }]
    }
  };

  const modified = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [
        { id: "asst1", name: "Changed Name" },
        { id: "asst2", name: "Assistant 2" }
      ],
      integrations: [{ id: "int1", name: "Integration 1" }]
    }
  };

  // Compare with nested fields configuration
  const diff = getDiff(original, modified, {
    compare: {
      tools: {
        assistants: ["id"],
        integrations: ["id"]
      }
    }
  });

  // Since only IDs are compared and IDs haven't changed, integrations should not appear in the diff
  // assistants shouldn't appear either since the IDs are the same
  expect(diff).toEqual({});
});

test("Detect change from null to object with nested comparison", () => {
  const a = { id: "1", completion_model: null as { id: string; name: string } | null };
  const b = { id: "1", completion_model: { id: "model-1", name: "GPT-4" } };

  expect(getDiff(a, b, { compare: { completion_model: { id: true } } })).toEqual({
    completion_model: { id: "model-1" }
  });
});

test("Detect change from undefined to object with nested comparison", () => {
  const a = { id: "1", completion_model: undefined as { id: string; name: string } | undefined };
  const b = { id: "1", completion_model: { id: "model-1", name: "GPT-4" } };

  expect(getDiff(a, b, { compare: { completion_model: { id: true } } })).toEqual({
    completion_model: { id: "model-1" }
  });
});

test("No change when both null", () => {
  const a = { id: "1", completion_model: null as { id: string } | null };
  const b = { id: "1", completion_model: null as { id: string } | null };

  expect(getDiff(a, b, { compare: { completion_model: { id: true } } })).toEqual({});
});

test("Detect change from null to value with full comparison", () => {
  const a = { id: "1", name: null as string | null };
  const b = { id: "1", name: "test" };

  expect(getDiff(a, b, { compare: { name: true } })).toEqual({ name: "test" });
});

test("Multiple nested properties with changes", () => {
  const original = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [{ id: "asst1", name: "Assistant 1" }],
      integrations: [{ id: "int1", name: "Integration 1" }]
    }
  };

  const modified = {
    id: "1",
    name: "group1",
    tools: {
      assistants: [{ id: "asst1", name: "Assistant 1" }],
      integrations: [{ id: "int2", name: "Integration 2" }]
    }
  };

  // Compare with nested fields configuration
  const diff = getDiff(original, modified, {
    compare: {
      tools: {
        assistants: ["id"],
        integrations: ["id"]
      }
    }
  });

  // Only integrations have changed
  expect(diff).toEqual({
    tools: {
      integrations: [{ id: "int2" }]
    }
  });
});
