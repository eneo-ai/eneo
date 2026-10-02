import { m } from "$lib/paraglide/messages";

export type RuntimeDiagnostics = {
  configured: boolean;
  state: "not_configured" | "ready" | "unreachable" | "unauthorized" | "unverified";
  expected_version: string;
  version?: string | null;
  warnings: string[];
};

export function runtimeMessages(status: RuntimeDiagnostics): string[] {
  const states = {
    not_configured: m.tools_runtime_not_configured,
    ready: m.tools_runtime_ready,
    unreachable: m.tools_runtime_unreachable,
    unauthorized: m.tools_runtime_unauthorized,
    unverified: m.tools_runtime_unverified
  };
  const warnings: Record<string, () => string> = {
    version_mismatch: m.tools_runtime_mismatch,
    revision_mismatch: m.tools_runtime_mismatch,
    unverified: m.tools_runtime_unverified,
    confinement_unavailable: m.tools_runtime_confinement,
    file_origin_unreachable: m.tools_runtime_file_origin,
    file_origin_not_allowed: m.tools_runtime_file_origin,
    file_origin_unknown: m.tools_runtime_file_origin
  };
  return [
    ...new Set([
      (states[status.state] ?? m.tools_runtime_unverified)(),
      ...(status.warnings ?? []).flatMap((warning) =>
        warnings[warning] ? [warnings[warning]()] : []
      )
    ])
  ];
}
