// The repository's label vocabulary and classification rules. Both setup and
// validation consume this owner; labels outside this catalog are left alone.

/** @typedef {'change' | 'area' | 'kind' | 'signal' | 'triage' | 'documentation'} LabelRole */
/** @type {ReadonlyArray<{name: string, color: string, description: string, roles: LabelRole[]}>} */
export const LABELS = [
  { name: "bug", color: "d73a4a", description: "Something is not working as intended", roles: ["change"] },
  { name: "enhancement", color: "a2eeef", description: "New or improved product behavior", roles: ["change"] },
  { name: "dependencies", color: "0366d6", description: "Dependency updates", roles: ["change"] },
  { name: "refactor", color: "8a63d2", description: "Code restructuring without intended behavior changes", roles: ["change"] },
  { name: "kind:chore", color: "cfd3d7", description: "Maintenance work without direct product behavior", roles: ["change", "kind"] },
  { name: "documentation", color: "0075ca", description: "Documentation changes; also the change type for documentation-only work", roles: ["documentation", "area"] },
  { name: "backend", color: "0e8a16", description: "Backend changes", roles: ["area"] },
  { name: "frontend", color: "5319e7", description: "Frontend changes", roles: ["area"] },
  { name: "infra", color: "d4a72c", description: "Infrastructure, operations, or deployment changes", roles: ["area"] },
  { name: "ci", color: "5319e7", description: "CI and automation changes", roles: ["area"] },
  { name: "github-actions", color: "1d76db", description: "GitHub Actions workflow updates", roles: ["area"] },
  { name: "docker", color: "0e8a16", description: "Container image or Dockerfile updates", roles: ["area"] },
  { name: "devcontainer", color: "c5def5", description: "Development container updates", roles: ["area"] },
  { name: "python:uv", color: "2b67c6", description: "Python dependencies managed with uv", roles: ["signal"] },
  { name: "security", color: "d73a4a", description: "Security-sensitive work or vulnerability tracking", roles: ["area", "signal"] },
  { name: "accessibility", color: "006b75", description: "Accessibility barriers or WCAG conformance work", roles: ["signal"] },
  { name: "breaking-change", color: "b60205", description: "Requires consumer or operator changes when upgrading", roles: ["signal"] },
  { name: "kind:epic", color: "5319e7", description: "Roadmap-level planning item that can own development tasks", roles: ["kind"] },
  { name: "kind:task", color: "1d76db", description: "Buildable development work item that should belong to an epic", roles: ["kind"] },
  { name: "kind:finding", color: "d4c5f9", description: "Observed issue, risk, or improvement candidate before planning", roles: ["kind"] },
  { name: "needs:epic", color: "fbca04", description: "Development task is not yet a sub-issue of an epic", roles: ["triage"] },
  { name: "needs:task-link", color: "fbca04", description: "Ready PR into develop closes no issue: link it under Development or write Fixes #123", roles: ["triage"] },
  { name: "needs:triage", color: "fef2c0", description: "Needs product or engineering triage before planning", roles: ["triage"] },
];

export const CHANGE_LABELS = LABELS.filter((label) => label.roles.includes("change")).map((label) => label.name);
export const AREA_LABELS = LABELS.filter((label) => label.roles.includes("area")).map((label) => label.name);
const ISSUE_KIND_LABELS = LABELS.filter((label) => label.roles.includes("kind")).map((label) => label.name);

export const ISSUE_AREAS = new Map([
  ["Backend", "backend"],
  ["Frontend", "frontend"],
  ["Infra", "infra"],
  ["Docs", "documentation"],
  ["Security", "security"],
]);

/** Evaluate explicit labels only. Never guess a change type from a title. */
export function evaluatePullRequest(labels) {
  const names = new Set(labels.map((name) => name.toLowerCase()));
  const types = CHANGE_LABELS.filter((name) => names.has(name));
  const areas = AREA_LABELS.filter((name) => names.has(name));
  const errors = [];

  // Documentation can accompany any primary change type. With no primary
  // type, it explicitly classifies documentation-only work in both dimensions.
  const changeType = types.length === 1 ? types[0]
    : types.length === 0 && names.has("documentation") ? "documentation" : null;
  if (types.length > 1) {
    errors.push(`Choose one primary change type; found ${types.join(", ")}. Split unrelated work into separate PRs.`);
  } else if (!changeType) {
    errors.push(`Add one change-type label: ${CHANGE_LABELS.join(", ")}, or documentation for documentation-only work.`);
  }
  if (areas.length === 0) {
    errors.push(`Add at least one area label: ${AREA_LABELS.join(", ")}.`);
  }
  return { ok: errors.length === 0, changeType, areas, errors };
}

/** Synchronize the explicit issue-form area, preserving unrelated labels. */
export function issueLabelChanges({ body, previousBody, labels }) {
  const names = new Set(labels.map((name) => name.toLowerCase()));
  const selected = getSectionWithPresence(body, ["Area"]);
  const area = ISSUE_AREAS.get(selected.value);
  const previousArea = previousBody === undefined ? undefined
    : ISSUE_AREAS.get(getSectionWithPresence(previousBody, ["Area"]).value);
  const add = [];
  const remove = [];
  if (previousArea && previousArea !== area && names.has(previousArea)) {
    remove.push(previousArea);
    names.delete(previousArea);
  }
  if (area && !names.has(area)) {
    add.push(area);
    names.add(area);
  }
  const hasKind = [...ISSUE_KIND_LABELS, ...CHANGE_LABELS, "documentation"].some((name) => names.has(name));
  const hasArea = AREA_LABELS.some((name) => names.has(name));
  if ((!hasKind || !hasArea || (selected.found && !area)) && !names.has("needs:triage")) {
    add.push("needs:triage");
  }
  // needs:triage can also mean a human has not reviewed a bug or finding.
  // Supplying classification must not silently complete that review.
  return { add, remove };
}

export function getSectionWithPresence(body, headings) {
  for (const heading of headings) {
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(
      `^#{2,6}\\s+${escaped}\\s*$([\\s\\S]*?)(?=^#{2,6}\\s+|$(?![\\s\\S]))`, "im",
    );
    const match = body.match(pattern);
    if (match) return { found: true, value: match[1].trim() };
  }
  return { found: false, value: "" };
}
