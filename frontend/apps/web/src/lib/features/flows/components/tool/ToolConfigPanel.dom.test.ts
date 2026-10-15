import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import type { ComponentProps } from "svelte";
import { readable } from "svelte/store";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";

import ToolConfigPanel from "./ToolConfigPanel.svelte";
import type { FlowToolOption, StoredToolInputConfig, ToolInputConfig } from "./toolInputConfig";

const space = vi.hoisted(() => ({ personal: false, mayEdit: false }));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        personal: space.personal,
        routeId: "space-1",
        hasPermission: () => space.mayEdit
      })
    }
  })
}));

// The command list scrolls the active option into view, which jsdom lacks.
beforeAll(() => {
  Element.prototype.scrollIntoView ??= vi.fn();
});

afterEach(async () => {
  cleanup();
  space.personal = false;
  space.mayEdit = false;
  await vi.waitFor(() => expect(document.body.style.overflow).not.toBe("hidden"));
});

function option(overrides: Partial<FlowToolOption>): FlowToolOption {
  return {
    mcp_server_id: "server-1",
    mcp_server_name: "Ärendesystemet",
    mcp_server_security_level: null,
    tool_id: "tool-search",
    tool_name: "search_cases",
    tool_description: "Söker ärenden.",
    input_schema: null,
    refusal: null,
    ...overrides
  };
}

function withSchema(input_schema: Record<string, unknown>): FlowToolOption {
  return option({ input_schema });
}

const SEARCH = withSchema({
  type: "object",
  required: ["query"],
  properties: {
    query: { type: "string", description: "Sökord" },
    limit: { type: "integer" },
    exact: { type: "boolean" },
    kind: { enum: ["open", 1] },
    tags: { type: "array" },
    note: { anyOf: [{ type: "string" }, { type: "null" }] }
  }
});
const REFUSED = option({
  tool_id: "tool-close",
  tool_name: "close_case",
  input_schema: { type: "object", additionalProperties: false },
  refusal: "tool_switched_off_in_space"
});

function chosen(args: Record<string, unknown> = {}, toolId = "tool-search"): StoredToolInputConfig {
  return { mcp_server_id: "server-1", tool_id: toolId, arguments: args, hasOtherKeys: false };
}

type PanelProps = ComponentProps<typeof ToolConfigPanel>;

/** The panel beside an editor that stores what the panel writes and hands it back. */
async function renderPanel(
  options: FlowToolOption[],
  config: StoredToolInputConfig | null,
  props: Partial<PanelProps> = {}
) {
  const onConfigChange = vi.fn<(detail: { config: ToolInputConfig }) => void>();
  const view = render(ToolConfigPanel, {
    config,
    toolOptions: { status: "loaded", options, classificationsEnabled: false, refreshing: false },
    stepKey: "step-2",
    isPublished: false,
    variableContext: {
      steps: [flowStepFixture({ user_description: "Hämta" })],
      currentStepOrder: 2,
      formSchema: undefined,
      isAdvancedMode: true,
      transcriptionEnabled: false
    },
    onConfigChange,
    ...props
  });
  const store = (next: ToolInputConfig) =>
    view.rerender({ config: { ...next, hasOtherKeys: false } });
  const atMount = onConfigChange.mock.lastCall?.[0].config;
  if (atMount) await store(atMount);
  // After the write, as a store does: a row may write while its effects run.
  onConfigChange.mockImplementation(({ config: next }) => queueMicrotask(() => void store(next)));
  /** The arguments of the configuration the panel wrote last. */
  const written = () => onConfigChange.mock.lastCall?.[0].config.arguments;
  return { ...view, onConfigChange, written };
}

const row = (name: string) => within(screen.getByRole("group", { name }));
const type = (input: HTMLElement, value: string) => fireEvent.input(input, { target: { value } });

describe("ToolConfigPanel", () => {
  // Kills: a refused tool can be chosen, is listed without its reason, or is
  // skipped by the arrow keys; the search matches an id; a chosen tool is
  // written with other ids or keeps another tool's arguments; choosing the
  // tool the step already has drops its arguments.
  it("lists a refused tool with its reason and writes only a tool that can be chosen", async () => {
    const { onConfigChange } = await renderPanel(
      [SEARCH, REFUSED, option({ tool_id: "tool-list", tool_name: "list_cases" })],
      chosen({ query: "bygglov" })
    );
    const open = () => fireEvent.click(screen.getByRole("combobox", { name: /search_cases/ }));

    await open();
    const refused = await screen.findByRole("option", { name: /close_case/ });
    expect(refused.getAttribute("aria-disabled")).not.toBe("true");
    expect(
      document.getElementById(refused.getAttribute("aria-describedby") ?? "")?.textContent
    ).toBe(m.flow_tool_refusal_tool_switched_off_in_space());
    await fireEvent.click(refused);
    await fireEvent.click(screen.getByRole("option", { name: /search_cases/ }));
    expect(onConfigChange).not.toHaveBeenCalled();

    await open();
    await type(screen.getByPlaceholderText(m.flow_tool_picker_search()), "tool-close");
    expect(screen.queryByRole("option", { name: /close_case/ })).toBeNull();
    await type(screen.getByPlaceholderText(m.flow_tool_picker_search()), "list_cases");
    await fireEvent.click(await screen.findByRole("option", { name: /list_cases/ }));
    expect(onConfigChange).toHaveBeenCalledExactlyOnceWith({
      config: { mcp_server_id: "server-1", tool_id: "tool-list", arguments: {} }
    });
  });

  // Kills: choosing the stored tool again leaves a choice with keys the server refuses.
  it("stores the choice the editor's way when the stored tool is chosen again", async () => {
    const { onConfigChange } = await renderPanel([SEARCH], {
      ...chosen({ query: "x" }),
      hasOtherKeys: true
    });
    await fireEvent.click(screen.getByRole("combobox", { name: /search_cases/ }));
    await fireEvent.click(await screen.findByRole("option", { name: /search_cases/ }));
    expect(onConfigChange).toHaveBeenCalledExactlyOnceWith({
      config: { mcp_server_id: "server-1", tool_id: "tool-search", arguments: { query: "x" } }
    });
  });

  // Kills: Variable mode stores text beside the token or takes typed text; a
  // fixed text that holds a variable is stored, or wiped from the input; an
  // argument without a chosen variable looks configured.
  it("binds an argument to exactly one variable and refuses a variable in a fixed text", async () => {
    const { written } = await renderPanel([SEARCH], chosen());
    const missing = m.flow_tool_argument_missing({ name: "query" });
    expect(row("query").getByText(missing)).toBeTruthy();

    const refusedText = "bygglov {{step_1.output.text}}";
    await type(row("query").getByRole("textbox"), refusedText);
    expect(row("query").getByText(m.flow_tool_argument_fixed_has_variable())).toBeTruthy();
    expect(row("query").getByRole("textbox")).toHaveProperty("value", refusedText);
    expect(written()).toEqual({});
    await type(row("query").getByRole("textbox"), "bygglov");
    expect(written()).toEqual({ query: "bygglov" });

    await fireEvent.click(row("query").getByText(m.flow_tool_argument_mode_variable()));
    expect(row("query").queryByRole("textbox")).toBeNull();
    expect(row("query").getByText(m.flow_tool_argument_variable_missing())).toBeTruthy();
    expect(row("query").getByText(missing)).toBeTruthy();
    await fireEvent.click(
      row("query").getByRole("button", { name: m.flow_tool_argument_choose_variable() })
    );
    expect(screen.queryByRole("option", { name: /\{\{step_1\.output\}\}/ })).toBeNull();
    await fireEvent.click(await screen.findByRole("option", { name: /step_1\.output\.text/ }));
    expect(written()).toEqual({ query: "{{step_1.output.text}}" });
  });

  // Kills: a number is stored as its text; a decimal or an integer too large
  // to be exact is stored, or refused without a word; a boolean is stored as
  // text or left out; "Not set" keeps the argument.
  it("stores a number as a number and a boolean as a boolean, and Not set removes the argument", async () => {
    const { written } = await renderPanel([SEARCH], chosen({ query: "x", limit: 3 }));
    const limit = () => row("limit").getByRole("spinbutton");

    for (const [text, sentence] of [
      ["2.5", m.flow_tool_argument_not_integer()],
      ["9007199254740993", m.flow_tool_argument_number_too_large()]
    ]) {
      await type(limit(), text);
      expect(row("limit").getByText(sentence)).toBeTruthy();
      expect(written()).toStrictEqual({ query: "x" });
    }
    await type(limit(), "25");
    expect(written()).toEqual({ query: "x", limit: 25 });

    await fireEvent.click(row("exact").getByText(m.flow_tool_argument_mode_fixed()));
    expect(written()).toEqual({ query: "x", limit: 25, exact: false });
    await fireEvent.click(row("exact").getByRole("switch"));
    expect(written()).toEqual({ query: "x", limit: 25, exact: true });

    await fireEvent.click(row("limit").getByText(m.flow_tool_argument_mode_unset()));
    expect(written()).toStrictEqual({ query: "x", exact: true });
  });

  // Kills: a choice is stored as its label's text; JSON that does not parse,
  // holds a number JSON cannot store or JavaScript cannot keep exactly, or a
  // variable inside a list is stored; a list is stored as text.
  it("stores a choice with its own type and a list only as valid JSON without a variable", async () => {
    const { written } = await renderPanel([SEARCH], chosen({ query: "x" }));

    await fireEvent.click(row("kind").getByText(m.flow_tool_argument_mode_fixed()));
    await fireEvent.keyDown(row("kind").getByRole("button", { name: /kind/ }), { key: "Enter" });
    await fireEvent.pointerUp(await screen.findByRole("option", { name: "1" }), {
      pointerType: "mouse",
      button: 0
    });
    expect(written()).toEqual({ query: "x", kind: 1 });

    await fireEvent.click(row("tags").getByText(m.flow_tool_argument_mode_fixed()));
    for (const [text, sentence] of [
      ['["a"', m.flow_tool_argument_json_invalid()],
      ["[1e999]", m.flow_tool_argument_number_too_large()],
      ["[9007199254740993]", m.flow_tool_argument_number_too_large()],
      ['["{{Hämta}}"]', m.flow_tool_argument_nested_reference({ argument: "tags" })]
    ]) {
      await type(row("tags").getByRole("textbox"), text);
      expect(row("tags").getByText(sentence)).toBeTruthy();
      expect(written()).toEqual({ query: "x", kind: 1 });
    }
    await type(row("tags").getByRole("textbox"), '["a"]');
    expect(written()).toEqual({ query: "x", kind: 1, tags: ["a"] });
  });

  // Kills: a row keeps showing a value, a kind of value or a control the step
  // and the tool no longer have; a stored value the tool no longer takes
  // looks fine; a deleted step's variable looks like any other.
  it("follows a value changed outside the row and a refreshed schema", async () => {
    const { rerender } = await renderPanel([SEARCH], chosen({ query: "abc", limit: 3 }));

    await type(row("query").getByRole("textbox"), "abcd");
    await rerender({ config: chosen({ query: "utifrån", limit: 3 }) });
    expect(row("query").getByRole("textbox")).toHaveProperty("value", "utifrån");
    await rerender({ config: chosen({ query: "{{step_9_deleted.output.text}}", limit: 3 }) });
    expect(row("query").queryByRole("textbox")).toBeNull();
    expect(row("query").getByText("{{step_9_deleted.output.text}}")).toBeTruthy();
    expect(row("query").getByText(m.flow_template_issue_deleted_step())).toBeTruthy();

    const refreshed = withSchema({
      properties: { query: { type: "string" }, limit: { type: "string" } }
    });
    await rerender({
      toolOptions: {
        status: "loaded",
        options: [refreshed],
        classificationsEnabled: false,
        refreshing: false
      }
    });
    expect(row("limit").getByRole("textbox")).toHaveProperty("value", "");
    expect(row("limit").getByText(m.flow_tool_argument_misfit(), { exact: false })).toBeTruthy();
    expect(row("query").getByText(m.flow_tool_argument_mode_unset())).toBeTruthy();
  });

  // Kills: an argument named like a member every object has reads as set, or
  // cannot be set; a required yes/no argument shows "no" while it has no value.
  it("reads and writes arguments as the object's own keys, and stores the no a switch shows", async () => {
    const { written } = await renderPanel(
      [
        withSchema({
          required: ["constructor", "confirm"],
          properties: {
            constructor: { type: "string" },
            ["__proto__"]: { type: "string" },
            confirm: { type: "boolean" }
          }
        })
      ],
      chosen()
    );
    expect(written()).toEqual({ confirm: false });
    expect(
      row("constructor").getByText(m.flow_tool_argument_missing({ name: "constructor" }))
    ).toBeTruthy();

    await type(row("constructor").getByRole("textbox"), "a");
    await fireEvent.click(row("__proto__").getByText(m.flow_tool_argument_mode_fixed()));
    await type(row("__proto__").getByRole("textbox"), "b");
    expect(Object.entries(written() ?? {})).toEqual([
      ["confirm", false],
      ["constructor", "a"],
      ["__proto__", "b"]
    ]);
  });

  // Kills: an empty text removes the argument; a nullable argument cannot
  // hold null, or shows a stored null as no longer fitting.
  it("keeps an empty text and a null as values", async () => {
    const { written } = await renderPanel([SEARCH], chosen({ query: "x", note: null }));
    expect(row("note").getByRole("textbox")).toHaveProperty("value", "null");
    expect(row("note").queryByText(m.flow_tool_argument_misfit(), { exact: false })).toBeNull();

    await type(row("query").getByRole("textbox"), "");
    expect(written()).toStrictEqual({ note: null, query: "" });
    expect(row("query").getByText(m.flow_tool_argument_empty_text())).toBeTruthy();
  });

  // Kills: a schema the editor cannot split into rows, or an open one, reads
  // "takes no arguments" and its stored arguments as removed; an argument an
  // open schema takes beyond its named ones is called removed; the JSON field
  // stores text beside a variable or a number JavaScript cannot keep exactly.
  it("shows a schema it cannot split, or an open one, as one JSON field", async () => {
    for (const input_schema of [{ type: "object", additionalProperties: {} }, null]) {
      const view = await renderPanel([option({ input_schema })], chosen({ owner: "x" }));
      expect(screen.queryByText(m.flow_tool_no_arguments())).toBeNull();
      expect(screen.queryByText(m.flow_tool_arguments_removed_title())).toBeNull();
      expect(screen.getByRole("textbox", { name: m.flow_tool_arguments_title() })).toHaveProperty(
        "value",
        JSON.stringify({ owner: "x" }, null, 2)
      );
      view.unmount();
    }
    const named = await renderPanel([SEARCH], chosen({ query: "x", owner: "y" }));
    expect(
      screen.getByRole("textbox", { name: m.flow_tool_arguments_other_label() })
    ).toHaveProperty("value", JSON.stringify({ owner: "y" }, null, 2));
    expect(screen.queryByText(m.flow_tool_arguments_removed_title())).toBeNull();
    named.unmount();

    const { written } = await renderPanel([withSchema({ $ref: "#/$defs/Search" })], chosen());
    expect(screen.getByText(m.flow_tool_arguments_json_hint())).toBeTruthy();
    const field = screen.getByRole("textbox", { name: m.flow_tool_arguments_title() });
    await type(field, '{"query": "se {{Hämta}}"}');
    expect(
      screen.getByText(m.flow_tool_argument_composed_text({ argument: "query" }))
    ).toBeTruthy();
    await type(field, '{"id": 9007199254740993}');
    expect(screen.getByText(m.flow_tool_argument_number_too_large())).toBeTruthy();
    expect(written()).toBeUndefined();
    await type(field, '{"query": "{{Hämta}}", "limit": 5}');
    expect(written()).toEqual({ query: "{{Hämta}}", limit: 5 });
  });

  // Kills: an open schema with named arguments offers no way to add or bind an
  // argument of another name; the other-arguments field drops or overwrites
  // the named ones; a named argument is taken there a second time.
  it("takes arguments of other names beside the rows of an open schema", async () => {
    const open = withSchema({
      type: "object",
      properties: { query: { type: "string" } },
      additionalProperties: { type: "string" }
    });
    const { written } = await renderPanel([open], chosen({ query: "bygglov" }));
    const other = () => screen.getByRole("textbox", { name: m.flow_tool_arguments_other_label() });
    expect(screen.queryByRole("textbox", { name: m.flow_tool_arguments_other_label() })).toBeNull();
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_tool_arguments_other_title() })
    );
    expect(other()).toHaveProperty("value", "{}");

    await type(other(), '{"query": "x"}');
    expect(
      screen.getByText(m.flow_tool_argument_has_own_field({ argument: "query" }))
    ).toBeTruthy();
    expect(written()).toBeUndefined();
    await type(other(), '{"lang": "sv"}');
    expect(written()).toEqual({ query: "bygglov", lang: "sv" });
    await type(other(), '{"lang": "{{Hämta}}"}');
    expect(written()).toEqual({ query: "bygglov", lang: "{{Hämta}}" });
  });

  // Kills: a stored tool the space no longer lists is shown as if nothing were
  // chosen, its arguments disappear, or a read-only view says "choose another".
  it.each([{ isPublished: false }, { isPublished: true }])(
    "says when the saved tool is no longer among the space's tools (%o)",
    async ({ isPublished }) => {
      await renderPanel([REFUSED], chosen({ query: "bygglov" }, "tool-gone"), { isPublished });

      expect(screen.getByText(m.flow_tool_stored_missing(), { exact: false })).toBeTruthy();
      expect(
        screen.queryByText(m.flow_tool_stored_missing_action(), { exact: false }) !== null
      ).toBe(!isPublished);
      expect(screen.getByText('query: "bygglov"')).toBeTruthy();
      expect(
        screen.queryByRole("button", { name: m.flow_tool_argument_remove({ argument: "query" }) })
      ).toBeNull();
    }
  );

  // Kills: an argument the tool no longer has stays unseen or cannot be
  // removed; a closed schema with named arguments is offered arguments of
  // other names; a chosen tool that is refused now shows no reason.
  it("lists arguments the tool no longer has, and says why the chosen tool is refused", async () => {
    const closed = withSchema({
      properties: { query: { type: "string" } },
      additionalProperties: false
    });
    const rows = await renderPanel([closed], chosen({ query: "x", gone: 1 }));
    expect(screen.getByText(m.flow_tool_arguments_removed_title())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.flow_tool_argument_remove({ argument: "gone" }) })
    ).toBeTruthy();
    expect(screen.queryByText(m.flow_tool_arguments_other_title())).toBeNull();
    rows.unmount();

    const { written } = await renderPanel([REFUSED], chosen({ gone: 1 }, "tool-close"));

    expect(screen.getByText(m.flow_tool_refusal_tool_switched_off_in_space())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_tool_argument_remove({ argument: "gone" }) })
    );
    expect(written()).toStrictEqual({});
  });

  // Kills: a failed load shows nothing to try again with; asking for the list
  // again takes the rows away, or leaves the button pressable; a published
  // step can be edited.
  it("offers a retry after a failed load, keeps the rows while reloading, and locks a published step", async () => {
    const onReloadOptions = vi.fn();
    const { rerender } = await renderPanel([SEARCH], chosen({ query: "x" }), {
      toolOptions: { status: "failed", message: "Listan kunde inte hämtas." },
      onReloadOptions
    });
    expect(screen.getByText("Listan kunde inte hämtas.")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: m.retry() }));
    expect(onReloadOptions).toHaveBeenCalledOnce();

    await rerender({
      toolOptions: {
        status: "loaded",
        options: [SEARCH],
        classificationsEnabled: false,
        refreshing: true
      }
    });
    expect(row("query").getByRole("textbox")).toHaveProperty("value", "x");
    expect(screen.getByRole("button", { name: m.flow_tool_options_refresh() })).toHaveProperty(
      "disabled",
      true
    );

    await rerender({ isPublished: true });
    expect(screen.getByRole("combobox", { name: /search_cases/ })).toHaveProperty("disabled", true);
    expect(row("query").getByRole("textbox")).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: m.flow_tool_options_refresh() })).toBeNull();
  });

  // Kills: the chosen tool's server class is not shown or is named from
  // another level; a server without a class gets no sentence while classes
  // are on; a class or sentence shows while the organization has classes off.
  it.each([
    {
      enabled: true,
      level: 30,
      shown: () => [m.flow_tool_server_class({ name: "Känslig" }), m.flow_tool_server_class_rule()]
    },
    { enabled: true, level: null, shown: () => [m.flow_tool_server_no_class()] },
    { enabled: false, level: 30, shown: () => [] }
  ])(
    "says what the chosen tool's server may receive (classes on $enabled, level $level)",
    async ({ enabled, level, shown }) => {
      const classes = [
        { name: "Öppen", security_level: 10 },
        { name: "Känslig", security_level: 30 }
      ];
      const options = [option({ mcp_server_security_level: level })];
      await renderPanel(options, chosen(), {
        classifications: classes,
        toolOptions: {
          status: "loaded",
          options,
          classificationsEnabled: enabled,
          refreshing: false
        }
      });

      const sentences = [
        m.flow_tool_server_class({ name: "Känslig" }),
        m.flow_tool_server_class_rule(),
        m.flow_tool_server_no_class()
      ];
      expect(sentences.filter((text) => screen.queryByText(text) !== null)).toStrictEqual(shown());
    }
  );

  // Kills: a personal space shows the "administrator switches servers on"
  // sentence or a settings link; somebody who may not edit the space gets the link.
  it.each([
    { personal: true, mayEdit: true, sentence: () => m.flow_tool_refusal_space_is_personal() },
    { personal: false, mayEdit: true, sentence: () => m.flow_tool_options_empty_editor() },
    { personal: false, mayEdit: false, sentence: () => m.flow_tool_options_empty_admin() }
  ])(
    "says who can give a space without tools any (personal $personal, may edit $mayEdit)",
    async ({ personal, mayEdit, sentence }) => {
      Object.assign(space, { personal, mayEdit });
      await renderPanel([], null);

      expect(screen.getByText(sentence())).toBeTruthy();
      const link = screen.queryByRole("link", { name: m.flow_tool_options_open_settings() });
      expect(link?.getAttribute("href") ?? null).toBe(
        !personal && mayEdit ? "/spaces/space-1/settings" : null
      );
    }
  );
});
