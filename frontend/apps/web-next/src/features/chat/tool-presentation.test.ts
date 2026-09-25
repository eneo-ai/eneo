import { describe, expect, it } from "vitest";
import { isSkillCall, skillName, toolPresentation } from "./tool-presentation";

const t = (key: string, values?: Record<string, string>) =>
  `${key}${values?.query ? `:${values.query}` : ""}`;

describe("chat tool presentation", () => {
  it("labels a capability by purpose even when an external provider names the tool differently", () => {
    const call = {
      toolName: "look_up",
      input: { q: "weather" },
      providerMetadata: { eneo: { server_name: "Search Inc", purpose: "web_search" } }
    };
    expect(toolPresentation(call, t, false)).toMatchObject({
      label: "tool_web_search_query:weather",
      provider: "Search Inc"
    });
    expect(toolPresentation(call, t, true).label).toBe("tool_web_search_query_done:weather");
  });

  it("distinguishes image edits from new image generation", () => {
    const call = {
      toolName: "draw",
      input: { reference_images: ["ref"] },
      providerMetadata: { eneo: { server_name: "Image Inc", purpose: "image_generation" } }
    };
    expect(toolPresentation(call, t, false).label).toBe("tool_edit_image");
    expect(toolPresentation(call, t, true).label).toBe("tool_edit_image_done");
  });

  it("localizes Eneo's knowledge tools and keeps external tool titles", () => {
    const internal = {
      toolName: "describe_source",
      providerMetadata: { eneo: { server_name: "knowledge" } }
    };
    expect(toolPresentation(internal, t, true).label).toBe("tool_describe_source_done");
    expect(
      toolPresentation(
        {
          toolName: "describe_source",
          providerMetadata: { eneo: { server_name: "Other", title: "Inspect source" } }
        },
        t,
        true
      ).label
    ).toBe("Inspect source");
  });

  it("recognizes Skill activations by server and preserves the display name", () => {
    const skill = {
      toolName: "planning",
      providerMetadata: { eneo: { server_name: "skills", title: "Planning Skill" } }
    };
    expect(isSkillCall(skill)).toBe(true);
    expect(skillName(skill)).toBe("Planning Skill");
    expect(toolPresentation(skill, t, false).label).toBe("tool_activate_skill");
    expect(
      isSkillCall({ toolName: "planning", providerMetadata: { eneo: { server_name: "Other" } } })
    ).toBe(false);
  });
});
