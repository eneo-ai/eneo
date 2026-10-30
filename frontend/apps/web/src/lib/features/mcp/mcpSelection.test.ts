import { describe, expect, it } from "vitest";

import { sanitizeMcpSelection } from "./mcpSelection";

describe("sanitizeMcpSelection", () => {
  it("drops selected servers and tool overrides that are no longer available in the space", () => {
    expect(
      sanitizeMcpSelection({
        selectedServers: [
          {
            id: "server-disabled",
            name: "Disabled",
            tools: [{ id: "tool-disabled", is_enabled: false }]
          },
          {
            id: "server-time",
            name: "Old Time",
            tools: [{ id: "tool-current-time", is_enabled: true }]
          }
        ],
        selectedTools: [
          { tool_id: "tool-disabled", is_enabled: false },
          { tool_id: "tool-current-time", is_enabled: true }
        ],
        availableServers: [
          {
            id: "server-time",
            name: "Time",
            tools: [{ id: "tool-current-time", name: "get_current_time", is_enabled: true }]
          }
        ]
      })
    ).toEqual({
      selectedServers: [
        {
          id: "server-time",
          name: "Time",
          tools: [{ id: "tool-current-time", name: "get_current_time", is_enabled: true }]
        }
      ],
      selectedTools: [{ tool_id: "tool-current-time", is_enabled: true }]
    });
  });

  it("keeps tool overrides inside the selected server set only", () => {
    expect(
      sanitizeMcpSelection({
        selectedServers: [{ id: "server-time", tools: [] }],
        selectedTools: [
          { tool_id: "tool-current-time", is_enabled: true },
          { tool_id: "tool-orphan", is_enabled: true }
        ],
        availableServers: [
          {
            id: "server-time",
            tools: [{ id: "tool-current-time", is_enabled: true }]
          },
          {
            id: "server-weather",
            tools: [{ id: "tool-orphan", is_enabled: true }]
          }
        ]
      })
    ).toEqual({
      selectedServers: [
        {
          id: "server-time",
          tools: [{ id: "tool-current-time", is_enabled: true }]
        }
      ],
      selectedTools: [{ tool_id: "tool-current-time", is_enabled: true }]
    });
  });

  it("does not re-enable a previously disabled selected tool by reading space defaults", () => {
    expect(
      sanitizeMcpSelection({
        selectedServers: [
          {
            id: "server-time",
            tools: [{ id: "tool-current-time", is_enabled: false }]
          }
        ],
        selectedTools: [],
        availableServers: [
          {
            id: "server-time",
            tools: [{ id: "tool-current-time", is_enabled: true }]
          }
        ]
      })
    ).toEqual({
      selectedServers: [
        {
          id: "server-time",
          tools: [{ id: "tool-current-time", is_enabled: false }]
        }
      ],
      selectedTools: []
    });
  });
});
