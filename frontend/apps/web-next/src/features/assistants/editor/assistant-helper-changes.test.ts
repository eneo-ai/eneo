import { describe, expect, it } from "vitest";
import { testTranslator } from "@/test/i18n";
import {
  changeOf,
  changeState,
  proposalUsed,
  publishedBy,
  requestGate,
  settingInRequest,
  type AssistantChange,
  type GateContext,
  type SettingChange
} from "./assistant-helper-changes";
import { changedFields, fieldsChangedBetween } from "./assistant-helper-form";
import type { Assistant, AssistantUpdate } from "./use-assistant";

const assistant = (overrides: Record<string, unknown> = {}) =>
  ({
    id: "assistant-1",
    name: "Skolhjälpen",
    description: null,
    prompt: { text: "Svara kort." },
    completion_model: { id: "model-1", name: "claude-haiku" },
    completion_model_kwargs: { temperature: 0.2 },
    knowledge_mode: "tool",
    inline_file_text: false,
    ...overrides
  }) as unknown as Assistant;

describe("Where a change the helper made stands", () => {
  const temperature: AssistantChange = {
    changes: [
      { field: "completion_model_kwargs.temperature", before: 0.7, after: 0.2, tooLong: false }
    ],
    undo: { completion_model_kwargs: { temperature: 0.7 } }
  };

  it("can be undone while the setting has the change's value, and is undone once it is back", () => {
    expect(changeState(temperature, assistant())).toBe("current");
    expect(
      changeState(temperature, assistant({ completion_model_kwargs: { temperature: 0.7 } }))
    ).toBe("undone");
    expect(
      changeState(temperature, assistant({ completion_model_kwargs: { temperature: 0.5 } }))
    ).toBe("changed");
  });

  it("counts a model given to an assistant that had none as undone with the rest", () => {
    const change: AssistantChange = {
      changes: [
        { field: "name", before: "Hjälpen", after: "Skolhjälpen", tooLong: false },
        {
          field: "completion_model",
          before: null,
          after: { id: "model-1", name: "claude-haiku" },
          tooLong: false
        }
      ],
      // An update cannot take a model away: the undo leaves it.
      undo: { name: "Hjälpen" }
    };

    expect(changeState(change, assistant())).toBe("current");
    expect(changeState(change, assistant({ name: "Hjälpen" }))).toBe("undone");
  });

  it("cannot be undone without an undo request", () => {
    expect(changeState({ ...temperature, undo: null }, assistant())).toBe("permanent");
  });
});

describe("A proposal in use", () => {
  it("reads a cleared description as no text", () => {
    expect(
      proposalUsed(
        {
          changes: [{ field: "description", before: "Gammal", after: null, tooLong: false }],
          update: { description: null }
        },
        assistant({ description: "" })
      )
    ).toBe(true);
  });

  it("reads model settings left out of a request as the model's default", () => {
    const update = { completion_model_kwargs: { temperature: 0.2 } };
    expect(settingInRequest(update, "completion_model_kwargs.top_p")).toBeNull();
    expect(settingInRequest(update, "completion_model_kwargs.temperature")).toBe(0.2);
    expect(settingInRequest(update, "name")).toBeUndefined();
  });
});

describe("The settings the helper reaches beyond the first ones", () => {
  const collections = (...ids: string[]) => ids.map((id) => ({ id, name: `Samling ${id}` }));
  const withLists = (overrides: Record<string, unknown> = {}) =>
    assistant({
      groups: [{ id: "c1" }, { id: "c2" }],
      websites: [],
      integration_knowledge_list: [],
      mcp_servers: [],
      mcp_tools: [{ tool_id: "t1", is_enabled: true }],
      enabled_capabilities: ["web_search"],
      rerank_model_id: null,
      document_template: { mode: "default", template_id: null },
      data_retention_days: null,
      insight_enabled: false,
      published: false,
      ...overrides
    });

  it("reads a list as a set of ids, whatever the order and the names", () => {
    const proposal = {
      changes: [
        {
          field: "groups",
          before: collections("c1"),
          after: collections("c2", "c1"),
          tooLong: false
        }
      ],
      update: { groups: [{ id: "c1" }, { id: "c2" }] }
    };
    expect(proposalUsed(proposal, withLists())).toBe(true);
    expect(proposalUsed(proposal, withLists({ groups: [{ id: "c1" }] }))).toBe(false);
  });

  it("can undo a list while it has the change's entries, and is undone once it has the earlier ones", () => {
    const change: AssistantChange = {
      changes: [
        {
          field: "groups",
          before: collections("c1"),
          after: collections("c1", "c2"),
          tooLong: false
        }
      ],
      undo: { groups: [{ id: "c1" }] }
    };
    expect(changeState(change, withLists())).toBe("current");
    expect(changeState(change, withLists({ groups: [{ id: "c1" }] }))).toBe("undone");
    expect(changeState(change, withLists({ groups: [{ id: "c3" }] }))).toBe("changed");
  });

  it("reads a function by its purpose, the request's list of purposes included", () => {
    const change: AssistantChange = {
      changes: [
        {
          field: "enabled_capabilities",
          before: [{ id: "web_search", name: "web search" }],
          after: [
            { id: "charts", name: "charts" },
            { id: "web_search", name: "web search" }
          ],
          tooLong: false
        }
      ],
      undo: { enabled_capabilities: ["web_search"] }
    };
    expect(changeState(change, withLists({ enabled_capabilities: ["web_search", "charts"] }))).toBe(
      "current"
    );
    expect(changeState(change, withLists())).toBe("undone");
  });

  it("reads the tool settings by tool and state", () => {
    const change: AssistantChange = {
      changes: [
        {
          field: "mcp_tools",
          before: [{ id: "t1", name: "search", is_enabled: true }],
          after: [{ id: "t1", name: "search", is_enabled: false }],
          tooLong: false
        }
      ],
      undo: { mcp_tools: [{ tool_id: "t1", is_enabled: true }] }
    };
    expect(
      changeState(change, withLists({ mcp_tools: [{ tool_id: "t1", is_enabled: false }] }))
    ).toBe("current");
    expect(changeState(change, withLists())).toBe("undone");
    // Back to the server's own setting: neither the change nor what it undoes.
    expect(changeState(change, withLists({ mcp_tools: [] }))).toBe("changed");
  });

  it("reads the ranking model by its id, and none as none", () => {
    const change: AssistantChange = {
      changes: [
        {
          field: "rerank_model_id",
          before: null,
          after: { id: "r1", name: "Rankaren" },
          tooLong: false
        }
      ],
      undo: { rerank_model_id: null }
    };
    expect(changeState(change, withLists({ rerank_model_id: "r1" }))).toBe("current");
    expect(changeState(change, withLists())).toBe("undone");
    expect(changeState(change, withLists({ rerank_model_id: "r2" }))).toBe("changed");
    expect(
      proposalUsed(
        { changes: change.changes, update: { rerank_model_id: "r1" } },
        withLists({ rerank_model_id: "r1" })
      )
    ).toBe(true);
  });

  it("reads retention, where none follows the space, and the insights switch", () => {
    const retention: AssistantChange = {
      changes: [{ field: "data_retention_days", before: null, after: 30, tooLong: false }],
      undo: { data_retention_days: null }
    };
    expect(changeState(retention, withLists({ data_retention_days: 30 }))).toBe("current");
    expect(changeState(retention, withLists())).toBe("undone");
    expect(changeState(retention, withLists({ data_retention_days: 60 }))).toBe("changed");

    const insights: AssistantChange = {
      changes: [{ field: "insight_enabled", before: false, after: true, tooLong: false }],
      undo: { insight_enabled: false }
    };
    expect(changeState(insights, withLists({ insight_enabled: true }))).toBe("current");
    expect(changeState(insights, withLists())).toBe("undone");
    expect(
      proposalUsed(
        { changes: insights.changes, update: { insight_enabled: true } },
        withLists({ insight_enabled: true })
      )
    ).toBe(true);
  });

  it("reads a template by its mode and template", () => {
    const after = { mode: "selected", template_id: "tpl-1", name: "Kommunens mall" };
    const proposal = {
      changes: [
        {
          field: "document_template",
          before: { mode: "default", template_id: null, name: null },
          after,
          tooLong: false
        }
      ],
      update: { document_template: { mode: "selected" as const, template_id: "tpl-1" } }
    };
    expect(
      proposalUsed(
        proposal,
        withLists({ document_template: { mode: "selected", template_id: "tpl-1" } })
      )
    ).toBe(true);
    expect(proposalUsed(proposal, withLists())).toBe(false);
  });
});

describe("A publish by the helper", () => {
  const call = (published: boolean) => ({
    toolName: "publish_assistant",
    serverName: "assistant",
    isInternal: true,
    structuredContent: {
      target_id: "assistant-1",
      changes: [{ field: "published", before: !published, after: published }],
      undo: null
    }
  });

  it("is a change with no undo, and says which way it went", () => {
    const change = changeOf(call(true), "assistant-1")!;
    expect(change.undo).toBeNull();
    expect(publishedBy(change)).toBe(true);
    expect(publishedBy(changeOf(call(false), "assistant-1")!)).toBe(false);
    expect(changeState(change, assistant({ published: true }))).toBe("permanent");
    expect(changedFields(change.changes)).toEqual(["published"]);
  });

  it("is not read from another assistant's call or another server", () => {
    expect(changeOf(call(true), "assistant-2")).toBeNull();
    expect(changeOf({ ...call(true), serverName: "flows" }, "assistant-1")).toBeNull();
    // A change of settings is not a publish.
    expect(
      publishedBy({
        changes: [{ field: "name", before: "A", after: "B", tooLong: false }],
        undo: { name: "A" }
      })
    ).toBeNull();
  });
});

describe("What a change names for the form's marks", () => {
  it("names each function switched on its own, and any other setting once", () => {
    expect(
      changedFields([
        {
          field: "enabled_capabilities",
          before: [{ id: "web_search", name: "web search" }],
          after: [{ id: "charts", name: "charts" }],
          tooLong: false
        },
        {
          field: "groups",
          before: [{ id: "c1", name: "A" }],
          after: [{ id: "c1", name: "A" }],
          tooLong: false
        },
        { field: "mcp_servers", before: [], after: [{ id: "s1", name: "Ärenden" }], tooLong: false }
      ])
    ).toEqual(["enabled_capabilities.charts", "enabled_capabilities.web_search", "mcp_servers"]);
  });

  it("reads the same between two readings of the assistant", () => {
    const before = assistant({ enabled_capabilities: ["web_search"], data_retention_days: null });
    const after = assistant({
      enabled_capabilities: ["web_search", "charts"],
      data_retention_days: 30
    });
    expect(
      fieldsChangedBetween(["enabled_capabilities", "data_retention_days", "name"], before, after)
    ).toEqual(["enabled_capabilities.charts", "data_retention_days"]);
  });
});

describe("Who may send a request: the editor's own conditions (decision 10)", () => {
  const t = testTranslator();
  const SERVER = { id: "s1", name: "Ärenden", is_enabled: true, purpose: "custom", tools: [] };
  const TOOLS_MODEL = { id: "model-1", name: "claude-haiku", supports_tool_calling: true };
  const PLAIN_MODEL = { id: "model-2", name: "plain-model", supports_tool_calling: false };
  const context = (
    overrides: Omit<Partial<GateContext>, "space"> & { space?: Record<string, unknown> } = {}
  ) => {
    const { space, ...rest } = overrides;
    return {
      space: {
        personal: false,
        completion_models: [TOOLS_MODEL, PLAIN_MODEL],
        mcp_servers: [SERVER],
        enabled_capabilities: ["web_search", "charts"],
        available_capabilities: [
          { purpose: "web_search", available: true },
          { purpose: "charts", available: true }
        ],
        ...space
      },
      canEditSpace: true,
      ...rest
    } as unknown as GateContext;
  };
  const editor = (overrides: Record<string, unknown> = {}) =>
    assistant({
      permissions: ["read", "edit"],
      completion_model: TOOLS_MODEL,
      groups: [],
      websites: [],
      integration_knowledge_list: [],
      mcp_servers: [],
      mcp_tools: [],
      enabled_capabilities: [],
      effective_config: null,
      ...overrides
    });
  const reason = (
    body: AssistantUpdate,
    who: Assistant = editor(),
    where: GateContext = context(),
    changes: SettingChange[] = []
  ) => {
    const gate = requestGate(body, changes, who, where, t);
    return gate.offered ? gate.disabledReason : "not offered";
  };

  it("offers nothing without edit rights", () => {
    expect(
      reason({ insight_enabled: true }, editor({ permissions: ["read", "insight_toggle"] }))
    ).toBe("not offered");
  });

  it("holds retention to someone who may edit the space, outside a personal space", () => {
    const retention = { data_retention_days: 30 };
    expect(reason(retention, editor(), context({ canEditSpace: false }))).toBe(
      "Endast administratörer för utrymmet kan ändra gallringen."
    );
    expect(reason(retention)).toBeNull();
    expect(
      reason(retention, editor(), context({ canEditSpace: false, space: { personal: true } }))
    ).toBeNull();
  });

  it("holds the insights switch to the right to toggle insights", () => {
    expect(reason({ insight_enabled: true })).toBe(
      "Endast ytans administratörer kan växla insikter."
    );
    expect(
      reason({ insight_enabled: true }, editor({ permissions: ["edit", "insight_toggle"] }))
    ).toBeNull();
  });

  it("holds the MCP servers, their tools and the functions where a policy governs them", () => {
    const governed = editor({ effective_config: { mcp_enforced: true } });
    expect(reason({ mcp_servers: [{ id: "s1" }] }, governed)).toBe(
      "MCP-servrar styrs av organisationens policy och kan inte ändras här."
    );
    expect(reason({ mcp_tools: [{ tool_id: "t1", is_enabled: false }] }, governed)).toBe(
      "MCP-servrar styrs av organisationens policy och kan inte ändras här."
    );
    expect(reason({ enabled_capabilities: [] }, governed)).toBe(
      "Funktioner styrs av organisationens policy och kan inte ändras här."
    );
  });

  it("keeps knowledge and MCP servers apart as the editor's pickers do", () => {
    const withServer = editor({ mcp_servers: [SERVER] });
    const withKnowledge = editor({ groups: [{ id: "c1" }] });
    expect(reason({ groups: [{ id: "c1" }] }, withServer)).toBe(
      "Kunskap är inte tillgänglig när MCP-servrar är aktiverade. Ta bort MCP-servrar för att aktivera kunskap."
    );
    expect(reason({ mcp_servers: [{ id: "s1" }] }, withKnowledge)).toBe(
      "MCP-servrar är inte tillgängliga när kunskap (samlingar, webbplatser, integrationer) är bifogad. Ta bort kunskap för att aktivera MCP-servrar."
    );
    // The editor lets the person take the servers away first, then add knowledge.
    expect(reason({ mcp_servers: [], groups: [{ id: "c1" }] }, withServer)).toBeNull();
    // Taking the knowledge away is always open.
    expect(
      reason({ groups: [] }, editor({ groups: [{ id: "c1" }], mcp_servers: [SERVER] }))
    ).toBeNull();
  });

  it("does not switch on a server, a tool or a function while the model cannot call tools", () => {
    const plain = editor({ completion_model: PLAIN_MODEL });
    expect(reason({ mcp_servers: [{ id: "s1" }] }, plain)).toBe(
      "Ärenden kan inte slås på. Modellen stödjer inte verktygsanrop."
    );
    expect(
      reason({ mcp_tools: [{ tool_id: "t1", is_enabled: true }] }, plain, context(), [
        {
          field: "mcp_tools",
          before: [],
          after: [{ id: "t1", name: "search_cases", is_enabled: true }],
          tooLong: false
        }
      ])
    ).toBe("search_cases kan inte slås på. Modellen stödjer inte verktygsanrop.");
    expect(reason({ enabled_capabilities: ["charts"] }, plain)).toBe(
      "Diagram kan inte slås på. Modellen stödjer inte verktygsanrop."
    );
    // Switching off is open, as in the editor.
    expect(reason({ mcp_tools: [{ tool_id: "t1", is_enabled: false }] }, plain)).toBeNull();
    expect(
      reason(
        { enabled_capabilities: [] },
        editor({ completion_model: PLAIN_MODEL, enabled_capabilities: ["charts"] })
      )
    ).toBeNull();
    // A request that also chooses a model that can call tools is read with that model.
    expect(
      reason({ completion_model: { id: TOOLS_MODEL.id }, enabled_capabilities: ["charts"] }, plain)
    ).toBeNull();
  });

  it("does not switch on a server the space does not offer or an administrator turned off", () => {
    expect(
      reason({ mcp_servers: [{ id: "s9" }] }, editor(), context(), [
        { field: "mcp_servers", before: [], after: [{ id: "s9", name: "Arkivet" }], tooLong: false }
      ])
    ).toBe("Ytan erbjuder inte Arkivet.");
    expect(
      reason(
        { mcp_servers: [{ id: "s1" }] },
        editor(),
        context({ space: { mcp_servers: [{ ...SERVER, is_enabled: false }] } })
      )
    ).toBe("Ärenden kan inte slås på. Verktyget är inaktiverat av administratören.");
    expect(reason({ mcp_servers: [{ id: "s1" }] })).toBeNull();
  });

  it("does not switch on a function the space does not offer or no provider is ready for", () => {
    expect(reason({ enabled_capabilities: ["compute"] })).toBe(
      "Beräkning kan inte slås på. Funktionen är avstängd i ytans inställningar."
    );
    expect(
      reason(
        { enabled_capabilities: ["charts"] },
        editor(),
        context({ space: { available_capabilities: [{ purpose: "charts", available: false }] } })
      )
    ).toBe("Diagram kan inte slås på. Ingen källa är aktiv.");
    expect(reason({ enabled_capabilities: ["charts"] })).toBeNull();
  });

  it("does not choose a ranking model or a template the editor no longer offers", () => {
    const rerank = [
      {
        field: "rerank_model_id",
        before: null,
        after: { id: "r9", name: "Gammal rankare" },
        tooLong: false
      }
    ];
    expect(
      reason({ rerank_model_id: "r9" }, editor(), context({ rerankModels: [{ id: "r1" }] }), rerank)
    ).toBe("Gammal rankare kan inte väljas för den här assistenten.");
    expect(
      reason({ rerank_model_id: "r1" }, editor(), context({ rerankModels: [{ id: "r1" }] }))
    ).toBeNull();
    // Not known yet: the server has the last word.
    expect(reason({ rerank_model_id: "r9" })).toBeNull();

    const template = { document_template: { mode: "selected" as const, template_id: "tpl-9" } };
    const named = [
      {
        field: "document_template",
        before: { mode: "default", template_id: null, name: null },
        after: { mode: "selected", template_id: "tpl-9", name: "Gamla mallen" },
        tooLong: false
      }
    ];
    expect(reason(template, editor(), context({ templates: [{ id: "tpl-1" }] }), named)).toBe(
      "Gamla mallen finns inte längre bland organisationens mallar."
    );
    expect(
      reason(
        { document_template: { mode: "builtin", template_id: null } },
        editor(),
        context({ templates: [] })
      )
    ).toBeNull();
  });
});
