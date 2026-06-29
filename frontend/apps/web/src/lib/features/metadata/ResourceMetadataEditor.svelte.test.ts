import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import type { ResourceMetadataJson, TenantMetadataField } from "@intric/intric-js";
import ResourceMetadataEditor from "./ResourceMetadataEditor.svelte";

describe("ResourceMetadataEditor", () => {
  it("drops stale tenant-owned eneo entries before the next save", async () => {
    const onChange = vi.fn();
    const metadataJson: ResourceMetadataJson = {
      other: { keep: true },
      eneo: [
        { key: "visibleString", value: "keep me", type: "string" },
        { key: "hiddenField", value: "drop me", type: "string" },
        { key: "typeChanged", value: "drop me too", type: "string" },
        { key: "orphanField", value: "preserve me", type: "string" }
      ]
    };
    const tenantFields: TenantMetadataField[] = [
      {
        id: "1",
        tenant_id: "tenant-1",
        name: "visibleString",
        field_type: "string",
        visible_on_assistants: false,
        visible_on_spaces: true
      },
      {
        id: "2",
        tenant_id: "tenant-1",
        name: "hiddenField",
        field_type: "string",
        visible_on_assistants: false,
        visible_on_spaces: false
      },
      {
        id: "3",
        tenant_id: "tenant-1",
        name: "typeChanged",
        field_type: "int",
        visible_on_assistants: false,
        visible_on_spaces: true
      }
    ];

    const screen = render(ResourceMetadataEditor, {
      metadataJson,
      tenantFields,
      resourceType: "space",
      onChange
    });

    expect(screen.container.textContent).toContain("visibleString");
    expect(screen.container.textContent).toContain("typeChanged");
    expect(screen.container.textContent).not.toContain("hiddenField");
    expect(screen.container.textContent).not.toContain("orphanField");

    await page.getByLabelText("visibleString").fill("updated value");

    expect(onChange).toHaveBeenCalled();
    expect(onChange).toHaveBeenLastCalledWith({
      other: { keep: true },
      eneo: [
        { key: "orphanField", value: "preserve me", type: "string" },
        { key: "visibleString", value: "updated value", type: "string" }
      ]
    });
  });
});
