#!/usr/bin/env node

import fs from "node:fs";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

const args = parseArgs(process.argv.slice(2));
const selfTest = args["self-test"] === "true";
const owner = args.owner || process.env.PROJECT_OWNER || "eneo-ai";
const project = args.project || process.env.PROJECT_NUMBER || "5";
const limit = args.limit || "1000";
const format = args.format || "markdown";
const audience = args.audience || "default";
const versions = parseVersionList(args.versions || "");

if (selfTest) {
  runSelfTest();
  process.exit(0);
}

const data = args.input
  ? readInput(args.input)
  : readProjectItems({ owner, project, limit });

const epics = (data.items || [])
  .filter(isEpic)
  .map(toEpic)
  .sort(compareEpics);

const output = renderOutput(epics, { owner, project, format, audience, versions });

if (args.output) {
  fs.writeFileSync(args.output, output);
} else {
  process.stdout.write(output);
}

function renderOutput(epics, context) {
  if (context.format === "mermaid") {
    return renderMermaid(epics, context);
  }

  if (context.format === "svg") {
    return renderSvgRoadmap(epics, context);
  }

  if (context.format === "markdown") {
    return renderMarkdown(epics, context);
  }

  throw new Error(`Unsupported roadmap export format: ${context.format}`);
}

function readProjectItems({ owner, project, limit }) {
  const result = spawnSync("gh", [
    "project",
    "item-list",
    project,
    "--owner",
    owner,
    "--limit",
    limit,
    "--format",
    "json",
  ], {
    encoding: "utf8",
    env: process.env,
  });

  if (result.status !== 0) {
    process.stderr.write(result.stderr || "Failed to read GitHub Project items.\n");
    process.exit(result.status ?? 1);
  }

  return JSON.parse(result.stdout);
}

function readInput(path) {
  const source = path === "-" ? fs.readFileSync(0, "utf8") : fs.readFileSync(path, "utf8");
  return JSON.parse(source);
}

function isEpic(item) {
  const kind = getField(item, ["kind", "type"]);
  const labels = getLabels(item);
  const title = getTitle(item);
  const body = item.content?.body || "";

  if (isExplicitNonEpic(kind, labels)) {
    return false;
  }

  return equals(kind, "Epic")
    || equals(kind, "Initiative")
    || labels.some((label) => equals(label, "kind:epic"))
    || labels.some((label) => equals(label, "kind:initiative"))
    || /^\[(epic|initiative)\]/i.test(title)
    || Boolean(getField(item, ["roadmap version"]))
    || Boolean(getSectionValue(body, ["Roadmap version"]));
}

function isExplicitNonEpic(kind, labels) {
  const nonEpicKinds = ["task", "bug", "finding", "chore"];

  return nonEpicKinds.some((candidate) => equals(kind, candidate))
    || labels.some((label) => nonEpicKinds.some((candidate) => equals(label, `kind:${candidate}`)));
}

function toEpic(item, index) {
  const body = item.content?.body || "";
  const version = firstValue([
    getField(item, ["roadmap version", "version", "target version", "quarter"]),
    getSectionValue(body, ["Roadmap version", "Target version", "Version", "Quarter"]),
    "Unscheduled",
  ]);

  return {
    id: item.id || `epic-${index}`,
    number: item.content?.number,
    title: getTitle(item),
    url: item.content?.url,
    status: firstValue([getField(item, ["status"]), "Todo"]),
    priority: firstValue([
      getField(item, ["priority"]),
      getSectionValue(body, ["Priority"]),
      "",
    ]),
    area: firstValue([
      getField(item, ["area"]),
      getSectionValue(body, ["Area"]),
      "",
    ]),
    sponsor: firstValue([
      getField(item, ["sponsor / municipality", "sponsor", "municipality", "customer", "stakeholder"]),
      getSectionValue(body, ["Sponsor / municipality", "Sponsor", "Municipality", "Customer", "Stakeholder"]),
      "",
    ]),
    owner: firstValue([
      getField(item, ["owner / lead"]),
      getSectionValue(body, ["Owner / lead"]),
      "",
    ]),
    startDate: firstValue([
      getField(item, ["start date", "start"]),
      getSectionValue(body, ["Start date", "Start"]),
      "",
    ]),
    targetDate: firstValue([
      getField(item, ["target date", "target", "due date", "end date"]),
      getSectionValue(body, ["Target date", "Target", "Due date", "End date"]),
      "",
    ]),
    decisionNeeded: firstValue([
      getField(item, ["decision needed", "decision"]),
      getSectionValue(body, ["Decision needed", "Decision"]),
      "",
    ]),
    progress: firstValue([
      getField(item, ["sub-issue progress", "progress"]),
      getSectionValue(body, ["Sub-issue progress", "Progress"]),
      "",
    ]),
    version,
  };
}

function renderMarkdown(epics, context) {
  const lines = [
    "# Eneo roadmap",
    "",
    `Generated from GitHub Project ${context.owner}/${context.project}.`,
    "",
    "```mermaid",
    renderMermaid(epics, context),
    "```",
    "",
  ];

  if (context.audience === "committee") {
    lines.push(...renderCommitteeSnapshot(epics), "");
  }

  if (context.audience === "standup") {
    lines.push(...renderStandupSnapshot(epics), "");
  }

  lines.push(...renderVersionSections(epics, context));
  return lines.join("\n");
}

function renderMermaid(epics, context = { versions: [] }) {
  const configuredVersions = context.versions || [];
  const versions = roadmapVersions(epics, configuredVersions);

  if (epics.length === 0 && configuredVersions.length === 0) {
    return [
      "flowchart LR",
      "  empty[\"No epics found\"]",
    ].join("\n");
  }

  const lines = [
    "flowchart LR",
    "  classDef version fill:#f6f8fa,stroke:#57606a,color:#24292f,font-weight:bold",
    "  classDef done fill:#dafbe1,stroke:#1f883d,color:#24292f",
    "  classDef active fill:#ddf4ff,stroke:#0969da,color:#24292f",
    "  classDef blocked fill:#ffebe9,stroke:#cf222e,color:#24292f",
    "  classDef planned fill:#fff8c5,stroke:#9a6700,color:#24292f",
    "  classDef future fill:#f6f8fa,stroke:#57606a,color:#24292f",
  ];

  for (const version of versions) {
    lines.push(`  ${versionNodeId(version)}["${escapeMermaid(version)}"]:::version`);
  }

  for (const epic of epics) {
    const version = versionGroup(epic.version);
    const title = epic.number ? `#${epic.number} ${epic.title}` : epic.title;
    const detail = [epic.status, epic.sponsor, epic.owner ? `Owner: ${epic.owner}` : ""]
      .filter(Boolean)
      .join(" / ");
    const label = detail ? `${title}<br/>${detail}` : title;
    lines.push(`  ${epicNodeId(epic)}["${escapeMermaid(label)}"]:::${statusClass(epic)}`);
    lines.push(`  ${versionNodeId(version)} --> ${epicNodeId(epic)}`);
  }

  return lines.join("\n");
}

function renderCommitteeSnapshot(epics) {
  const decisionEpics = epics.filter(needsDecision);
  const withoutDecisions = epics.filter((epic) => !needsDecision(epic));

  return [
    "## Committee snapshot",
    "",
    ...renderSnapshotGroup("Needs decision", decisionEpics),
    ...renderSnapshotGroup("Blocked / at risk", withoutDecisions.filter(isBlocked)),
    ...renderSnapshotGroup("In progress", withoutDecisions.filter(isActive)),
    ...renderSnapshotGroup("Done", withoutDecisions.filter(isDone)),
    ...renderSnapshotGroup("Next up", withoutDecisions.filter(isPlanned)),
  ];
}

function renderStandupSnapshot(epics) {
  const blockedEpics = epics.filter(isBlocked);
  const withoutBlocked = epics.filter((epic) => !isBlocked(epic));

  return [
    "## Standup snapshot",
    "",
    ...renderSnapshotGroup("Blocked", blockedEpics),
    ...renderSnapshotGroup("Needs decision", withoutBlocked.filter(needsDecision)),
    ...renderSnapshotGroup("In progress", withoutBlocked.filter(isActive)),
  ];
}

function renderSnapshotGroup(title, epics) {
  if (epics.length === 0) {
    return [];
  }

  return [
    `### ${title}`,
    "",
    ...epics.map(renderEpicBullet),
    "",
  ];
}

function renderVersionSections(epics, context) {
  const versions = roadmapVersions(epics, context.versions);
  const lines = [];

  for (const version of versions) {
    lines.push(`## ${version}`);
    lines.push("");

    for (const epic of epics.filter((candidate) => versionGroup(candidate.version) === version)) {
      lines.push(renderEpicBullet(epic));
    }

    lines.push("");
  }

  return lines;
}

function renderEpicBullet(epic) {
  const title = epic.url
    ? `[${escapeMarkdown(epic.title)}](${epic.url})`
    : escapeMarkdown(epic.title);
  const prefix = epic.number ? `#${epic.number} ` : "";
  const dates = [epic.startDate, epic.targetDate].filter(Boolean).join(" -> ");
  const meta = [
    epic.status,
    epic.priority,
    epic.area,
    epic.sponsor ? `Sponsor: ${epic.sponsor}` : "",
    epic.owner ? `Owner: ${epic.owner}` : "",
    epic.progress ? `Progress: ${epic.progress}` : "",
    dates ? `Dates: ${dates}` : "",
    needsDecision(epic) ? `Decision: ${epic.decisionNeeded}` : "",
  ].filter(Boolean).join(" / ");

  return `- ${prefix}${title}${meta ? ` - ${escapeMarkdown(meta)}` : ""}`;
}

function renderSvgRoadmap(epics, context) {
  const width = 1800;
  const height = 1000;
  const margin = 32;
  const headerHeight = 128;
  const footerHeight = 124;
  const contentTop = margin + headerHeight;
  const contentHeight = height - margin - footerHeight - contentTop;
  const svgEpics = svgAudienceEpics(epics, context.audience);
  const versions = roadmapVersions(svgEpics, context.versions);
  const columnWidth = (width - margin * 2) / versions.length;
  const itemsByVersion = new Map(
    versions.map((version) => [
      version,
      svgEpics.filter((epic) => versionGroup(epic.version) === version),
    ]),
  );

  const lines = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Eneo roadmap">`,
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#eef7f9"/>`,
  ];

  versions.forEach((version, index) => {
    const x = margin + index * columnWidth;
    const versionEpics = itemsByVersion.get(version) || [];
    const isDoneColumn = /^2\.0$/i.test(version)
      || (versionEpics.length > 0 && versionEpics.every(isDone));
    lines.push(`<rect x="${x}" y="${margin}" width="${columnWidth}" height="${height - margin * 2}" fill="${isDoneColumn ? "#c7ded1" : "#eef7f9"}"/>`);
    if (index > 0) {
      lines.push(`<line x1="${x}" y1="${margin}" x2="${x}" y2="${height - margin}" stroke="#9eb5be" stroke-width="1.5"/>`);
    }
    lines.push(`<text x="${x + columnWidth / 2}" y="${margin + 72}" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="#050505">${escapeXml(version)}</text>`);
  });

  for (const [version, versionEpics] of itemsByVersion) {
    const index = versions.indexOf(version);
    const x = margin + index * columnWidth;
    const futureColumn = isFutureVersion(version);
    const columns = versionEpics.length <= 3 || /^2\.0$/i.test(version) ? 1 : 2;
    const cardGap = columns === 1 ? 20 : 16;
    const rowGap = 24;
    const cardWidth = columns === 1
      ? Math.min(260, columnWidth - 92)
      : (columnWidth - 52 - cardGap) / 2;
    const cardHeight = 116;
    const startX = x + (columnWidth - (columns * cardWidth + (columns - 1) * cardGap)) / 2;
    const maxRows = Math.max(1, Math.floor((contentHeight + rowGap) / (cardHeight + rowGap)));
    const maxCards = maxRows * columns;
    const visibleEpics = versionEpics.length > maxCards
      ? versionEpics.slice(0, Math.max(0, maxCards - 1))
      : versionEpics;

    visibleEpics.forEach((epic, itemIndex) => {
      const row = Math.floor(itemIndex / columns);
      const col = itemIndex % columns;
      const cardX = startX + col * (cardWidth + cardGap);
      const cardY = contentTop + row * (cardHeight + rowGap);

      lines.push(...renderSvgCard(epic, {
        x: cardX,
        y: cardY,
        width: cardWidth,
        height: cardHeight,
        future: futureColumn || statusClass(epic) === "future",
      }));
    });

    if (visibleEpics.length < versionEpics.length) {
      const itemIndex = visibleEpics.length;
      const row = Math.floor(itemIndex / columns);
      const col = itemIndex % columns;
      const cardX = startX + col * (cardWidth + cardGap);
      const cardY = contentTop + row * (cardHeight + rowGap);
      lines.push(...renderSvgOverflowCard(versionEpics.length - visibleEpics.length, {
        x: cardX,
        y: cardY,
        width: cardWidth,
        height: cardHeight,
      }));
    }
  }

  const footerY = height - footerHeight + 18;
  const footer = svgFooterMeta(svgEpics, context);
  lines.push(`<line x1="0" y1="${footerY}" x2="${width}" y2="${footerY}" stroke="#003b16" stroke-width="2.5" stroke-dasharray="12 9"/>`);
  lines.push(`<line x1="0" y1="${footerY + 48}" x2="${width}" y2="${footerY + 48}" stroke="#003b16" stroke-width="2.5" stroke-dasharray="12 9"/>`);
  if (footer.attention) {
    const iconRadius = 24;
    const gap = 16;
    const footerTextWidth = textPixelWidth(footer.text, 11.5);
    const groupWidth = iconRadius * 2 + gap + footerTextWidth;
    const iconX = width / 2 - groupWidth / 2 + iconRadius;
    const textX = iconX + iconRadius + gap + footerTextWidth / 2;
    lines.push(`<circle cx="${iconX}" cy="${footerY + 24}" r="${iconRadius}" fill="#167c29" stroke="#053b12" stroke-width="3"/>`);
    lines.push(`<text x="${iconX}" y="${footerY + 33}" text-anchor="middle" font-family="Arial, sans-serif" font-size="32" font-weight="700" fill="#fff">!</text>`);
    lines.push(`<text x="${textX}" y="${footerY + 32}" text-anchor="middle" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0d4774">${escapeXml(footer.text)}</text>`);
  } else {
    lines.push(`<text x="${width / 2}" y="${footerY + 32}" text-anchor="middle" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0d4774">${escapeXml(footer.text)}</text>`);
  }
  lines.push(renderEneoLogo({
    x: width - margin - 232,
    y: height - margin - 66,
    width: 220,
    background: "#eef7f9",
  }));
  lines.push("</svg>");

  return lines.join("\n");
}

function renderSvgCard(epic, bounds) {
  const fill = bounds.future ? "#d8e8ee" : "#315f7a";
  const stroke = bounds.future ? "#003b16" : "#315f7a";
  const dash = bounds.future ? ' stroke-dasharray="12 9"' : "";
  const titleFill = bounds.future ? "#0d4774" : "#f8fbfd";
  const centerX = bounds.x + bounds.width / 2;
  const dot = statusDot(epic);
  const hasTopMeta = Boolean(epic.sponsor || dot);
  const titleFontSize = bounds.width < 190 ? 18 : 20;
  const lineHeight = titleFontSize + 4;
  const titleAreaTop = bounds.y + (hasTopMeta ? 42 : 20);
  const titleAreaBottom = bounds.y + bounds.height - (epic.owner ? 25 : 16);
  const titleAreaHeight = Math.max(titleFontSize, titleAreaBottom - titleAreaTop);
  const maxTitleLines = Math.max(1, Math.min(3, Math.floor(titleAreaHeight / lineHeight)));
  const titleMaxChars = Math.max(8, Math.floor((bounds.width - 28) / (titleFontSize * 0.56)));
  const titleLines = wrapText(epic.title, titleMaxChars, maxTitleLines);
  const titleBlockHeight = (titleLines.length - 1) * lineHeight;
  const titleStartY = titleAreaTop + titleAreaHeight / 2 - titleBlockHeight / 2 + titleFontSize * 0.35;
  const card = [
    `<rect x="${bounds.x}" y="${bounds.y}" width="${bounds.width}" height="${bounds.height}" rx="3" fill="${fill}" stroke="${stroke}" stroke-width="2.5"${dash}/>`,
  ];

  if (epic.sponsor) {
    const sponsor = sponsorDisplayName(epic.sponsor);
    const badgeX = bounds.x + 12;
    const badgeFontSize = sponsor.length > 13 ? 11 : 12;
    const badgeCharWidth = badgeFontSize * 0.53;
    const maxBadgeWidth = Math.max(48, bounds.width - (dot ? 62 : 24));
    const badgeText = truncateToWidth(sponsor, maxBadgeWidth - 18, badgeCharWidth);
    const badgeWidth = Math.min(maxBadgeWidth, Math.max(48, 18 + textPixelWidth(badgeText, badgeCharWidth)));
    card.push(`<rect x="${badgeX}" y="${bounds.y + 12}" width="${badgeWidth}" height="24" rx="4" fill="#244a62"/>`);
    card.push(`<text x="${badgeX + 9}" y="${bounds.y + 28}" font-family="Arial, sans-serif" font-size="${badgeFontSize}" font-weight="700" fill="#f8fbfd">${escapeXml(badgeText)}</text>`);
  }

  if (dot) {
    card.push(`<circle cx="${bounds.x + bounds.width - 28}" cy="${bounds.y + 28}" r="15" fill="${dot.fill}" stroke="${dot.stroke}" stroke-width="3"/>`);
  }

  titleLines.forEach((line, index) => {
    card.push(`<text x="${centerX}" y="${titleStartY + index * lineHeight}" text-anchor="middle" font-family="Arial, sans-serif" font-size="${titleFontSize}" font-weight="700" fill="${titleFill}">${escapeXml(line)}</text>`);
  });

  if (epic.owner) {
    const ownerFontSize = bounds.width < 190 ? 11 : 12;
    const ownerFill = bounds.future ? "#315f7a" : "#d8edf7";
    const ownerMaxWidth = bounds.width - 24;
    const ownerCharWidth = ownerFontSize * 0.55;
    const ownerWithLabel = `Owner: ${epic.owner}`;
    const ownerText = textPixelWidth(ownerWithLabel, ownerCharWidth) <= ownerMaxWidth
      ? ownerWithLabel
      : truncateToWidth(epic.owner, ownerMaxWidth, ownerCharWidth);
    card.push(`<text x="${centerX}" y="${bounds.y + bounds.height - 14}" text-anchor="middle" font-family="Arial, sans-serif" font-size="${ownerFontSize}" font-weight="700" fill="${ownerFill}">${escapeXml(ownerText)}</text>`);
  }

  return card;
}

function renderSvgOverflowCard(count, bounds) {
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;

  return [
    `<rect x="${bounds.x}" y="${bounds.y}" width="${bounds.width}" height="${bounds.height}" fill="#f6f8fa" stroke="#57606a" stroke-width="2.5" stroke-dasharray="10 8"/>`,
    `<text x="${centerX}" y="${centerY - 6}" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" font-weight="700" fill="#24292f">+${count} more</text>`,
    `<text x="${centerX}" y="${centerY + 24}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#57606a">see Markdown export</text>`,
  ];
}

function renderEneoLogo({ x, y, width, background }) {
  const fallback = `<text x="${x + width}" y="${y + 50}" text-anchor="end" font-family="Arial Black, Arial, sans-serif" font-size="58" font-weight="900" fill="#050505">eneo</text>`;

  try {
    const source = fs.readFileSync(new URL("../docs/assets/Eneo-logo-svg.svg", import.meta.url), "utf8");
    const match = source.match(/<svg\b[^>]*viewBox="([^"]+)"[^>]*>([\s\S]*?)<\/svg>/i);
    if (!match) {
      return fallback;
    }

    const [, viewBox, body] = match;
    const [, , viewBoxWidth, viewBoxHeight] = viewBox.split(/\s+/).map(Number);
    if (!viewBoxWidth || !viewBoxHeight) {
      return fallback;
    }

    const scale = width / viewBoxWidth;
    const height = viewBoxHeight * scale;

    return [
      `<rect x="${x - 12}" y="${y - 8}" width="${width + 24}" height="${height + 16}" fill="${background}"/>`,
      `<g transform="translate(${x} ${y}) scale(${scale})">`,
      body.trim(),
      "</g>",
    ].join("\n");
  } catch {
    return fallback;
  }
}

function sponsorDisplayName(value) {
  const text = String(value || "").trim();
  const normalized = text.toLowerCase();

  if (/^sundsvall(s|\b)/.test(normalized)) {
    return "Sundsvall";
  }

  if (/^(forsakringskassan|försäkringskassan)\b/.test(normalized)) {
    return "Forsakringskassan";
  }

  if (/^(orebro|örebro)\b/.test(normalized)) {
    return "Orebro";
  }

  if (/^(borlange|borlänge)\b/.test(normalized)) {
    return "Borlange";
  }

  return text
    .replace(/\s+(kommun|municipality)\b.*$/i, "")
    .trim() || text;
}

function svgAudienceEpics(epics, audience) {
  if (audience === "standup") {
    return epics.filter((epic) => isBlocked(epic) || needsDecision(epic) || isActive(epic));
  }

  return epics;
}

function roadmapVersions(epics, configuredVersions) {
  const configured = normalizeVersionList(configuredVersions || []);
  const base = configured.length > 0 ? configured : sortedVersions(epics, ["Unscheduled"]);
  const seen = new Set(base);
  const extras = [];

  for (const epic of epics) {
    const version = versionGroup(epic.version);
    if (!seen.has(version)) {
      seen.add(version);
      extras.push(version);
    }
  }

  return [...base, ...extras.sort(compareVersions)];
}

function normalizeVersionList(versions) {
  const normalized = versions.map(versionGroup).filter(Boolean);
  return [...new Set(normalized)];
}

function versionGroup(version) {
  const normalized = String(version || "").trim();
  if (/^(future|2\.x|2x)$/i.test(normalized)) {
    return "2.X";
  }
  return normalized || "Unscheduled";
}

function svgFooterMeta(epics, context) {
  if (context.audience === "standup") {
    return {
      attention: false,
      text: `${epics.length} active roadmap item${epics.length === 1 ? "" : "s"} for standup follow-up`,
    };
  }

  const decisionCount = epics.filter(needsDecision).length;
  if (decisionCount > 0) {
    return {
      attention: true,
      text: `${decisionCount} roadmap decision${decisionCount === 1 ? "" : "s"} need attention`,
    };
  }

  return {
    attention: false,
    text: "Roadmap snapshot from GitHub Project data",
  };
}

function statusDot(epic) {
  if (isDone(epic) || isActive(epic)) {
    return { fill: "#177c2d", stroke: "#052f12" };
  }

  if (isBlocked(epic)) {
    return { fill: "#cf222e", stroke: "#6e0e14" };
  }

  return null;
}

function needsDecision(epic) {
  const normalized = String(epic.decisionNeeded || "")
    .trim()
    .replace(/[.!]+$/g, "");

  return Boolean(normalized)
    && !/^(no|none|n\/a|na|nej|inget|ingen|no decision needed|no decision needed right now|not needed|not now|-)$/.test(normalized.toLowerCase());
}

function isDone(epic) {
  return /^(done|closed|complete|completed|merged)$/i.test(epic.status);
}

function isActive(epic) {
  return /^(in progress|doing|active|started|implementing)$/i.test(epic.status);
}

function isBlocked(epic) {
  return /(blocked|risk|at risk|paused|waiting)/i.test(epic.status);
}

function isPlanned(epic) {
  return !isDone(epic) && !isActive(epic) && !isBlocked(epic) && !isFutureVersion(epic.version);
}

function isFutureVersion(version) {
  return /^(future|2\.x|2x)$/i.test(String(version || "").trim());
}

function getField(item, names) {
  for (const [key, value] of Object.entries(item)) {
    if (names.some((name) => key.toLowerCase() === name.toLowerCase())) {
      return normalizeValue(value);
    }
  }

  return "";
}

function getSectionValue(body, headings) {
  for (const heading of headings) {
    const escaped = escapeRegExp(heading);
    const pattern = new RegExp(
      `^#{2,6}\\s+${escaped}\\s*$([\\s\\S]*?)(?=^#{2,6}\\s+|$(?![\\s\\S]))`,
      "im",
    );
    const match = body.match(pattern);

    if (!match) {
      continue;
    }

    const value = match[1]
      .replace(/<!--[\s\S]*?-->/g, "")
      .trim()
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)[0];

    if (value) {
      return value;
    }
  }

  return "";
}

function getLabels(item) {
  return (item.labels || []).map((label) => {
    if (typeof label === "string") {
      return label;
    }

    return label.name || "";
  }).filter(Boolean);
}

function getTitle(item) {
  return item.title || item.content?.title || "Untitled epic";
}

function firstValue(values) {
  return values.map(normalizeValue).find(Boolean) || "";
}

function normalizeValue(value) {
  if (value === null || value === undefined) {
    return "";
  }

  if (Array.isArray(value)) {
    return value.map(normalizeValue).filter(Boolean).join(", ");
  }

  if (typeof value === "object") {
    return value.name || value.title || "";
  }

  return String(value).trim();
}

function compareEpics(left, right) {
  return compareVersions(left.version, right.version)
    || comparePriority(left.priority, right.priority)
    || left.title.localeCompare(right.title);
}

function compareVersions(left, right) {
  const leftRank = versionRank(left);
  const rightRank = versionRank(right);

  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  return left.localeCompare(right);
}

function versionRank(version) {
  const normalized = String(version || "").toLowerCase();

  if (normalized === "unscheduled") {
    return 10_000;
  }

  if (normalized === "future" || normalized === "2.x" || normalized === "2x") {
    return 9_000;
  }

  const match = /^v?(\d+)(?:\.(\d+))?/.exec(normalized);

  if (!match) {
    return 8_000;
  }

  return Number(match[1]) * 100 + Number(match[2] || 0);
}

function comparePriority(left, right) {
  return priorityRank(left) - priorityRank(right);
}

function priorityRank(priority) {
  const match = /^p(\d)$/i.exec(priority || "");
  return match ? Number(match[1]) : 99;
}

function equals(left, right) {
  return String(left || "").toLowerCase() === String(right || "").toLowerCase();
}

function statusClass(epic) {
  if (isDone(epic)) {
    return "done";
  }

  if (isBlocked(epic)) {
    return "blocked";
  }

  if (isActive(epic)) {
    return "active";
  }

  if (isFutureVersion(epic.version)) {
    return "future";
  }

  return "planned";
}

function uniqueVersions(epics) {
  return [...new Set(epics.map((epic) => epic.version))];
}

function sortedVersions(epics, fallback) {
  const versions = uniqueVersions(epics).map(versionGroup).filter(Boolean);
  const unique = [...new Set(versions)];
  return unique.length > 0 ? unique.sort(compareVersions) : fallback;
}

function parseVersionList(value) {
  return String(value || "")
    .split(",")
    .map((version) => version.trim())
    .filter(Boolean);
}

function versionNodeId(version) {
  return `version_${slug(version)}`;
}

function epicNodeId(epic) {
  return `epic_${epic.number || slug(epic.id)}`;
}

function slug(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "unknown";
}

function wrapText(value, maxChars, maxLines) {
  const words = String(value).split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";

  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length <= maxChars) {
      current = next;
      continue;
    }

    if (current) {
      lines.push(current);
      current = word;
    } else {
      lines.push(word.slice(0, maxChars));
      current = word.slice(maxChars);
    }

    if (lines.length === maxLines) {
      break;
    }
  }

  if (current && lines.length < maxLines) {
    lines.push(current);
  }

  if (lines.length === maxLines && words.join(" ").length > lines.join(" ").length) {
    lines[maxLines - 1] = truncate(lines[maxLines - 1], maxChars);
  }

  return lines.length > 0 ? lines : [""];
}

function truncate(value, maxChars) {
  const text = String(value);
  return text.length <= maxChars ? text : `${text.slice(0, Math.max(0, maxChars - 3))}...`;
}

function truncateToWidth(value, maxWidth, averageCharWidth) {
  const maxChars = Math.max(1, Math.floor(maxWidth / averageCharWidth));
  return truncate(value, maxChars);
}

function textPixelWidth(value, averageCharWidth) {
  return String(value || "").length * averageCharWidth;
}

function escapeMermaid(value) {
  return String(value).replace(/"/g, "'");
}

function escapeMarkdown(value) {
  return String(value).replace(/\|/g, "\\|");
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function runSelfTest() {
  const items = [
    {
      id: "item-1",
      labels: ["kind:epic"],
      content: {
        number: 101,
        title: "Personlig chatt 2.0",
        url: "https://github.com/eneo-ai/eneo/issues/101",
        body: [
          "## Roadmap version",
          "2.7",
          "",
          "## Sponsor / municipality",
          "Sundsvalls kommun verksamhetsstod",
          "",
          "## Owner / lead",
          "Team Platform",
          "",
          "## Decision needed",
          "Need committee decision on rollout scope.",
        ].join("\n"),
      },
      Status: "In progress",
      Priority: "P1",
      Area: "Frontend",
    },
    {
      id: "item-2",
      labels: ["kind:epic"],
      content: {
        number: 102,
        title: "Extern kostnadsuppfoljning",
        body: "## Roadmap version\n2.7 RC\n",
      },
      Status: "Todo",
    },
    {
      id: "item-3",
      labels: ["kind:epic"],
      content: {
        number: 103,
        title: "Crawl 2.0",
        body: "## Roadmap version\nFuture\n## Owner / lead\nSearch\n",
      },
      Status: "Todo",
    },
    {
      id: "task-1",
      labels: ["kind:task"],
      content: {
        number: 201,
        title: "[Task]: child work",
        body: "## Parent epic\n#101\n",
      },
      Version: "2.7",
    },
  ];
  const epics = items.filter(isEpic).map(toEpic).sort(compareEpics);

  assert.equal(epics.length, 3, "generic Version fields must not turn tasks into roadmap epics");

  const markdown = renderOutput(epics, {
    owner: "eneo-ai",
    project: "5",
    format: "markdown",
    audience: "committee",
    versions: parseVersionList("2.6,2.7,2.7 RC,Future"),
  });

  assert.match(markdown, /## 2\.6/);
  assert.match(markdown, /## 2\.7/);
  assert.match(markdown, /## 2\.7 RC/);
  assert.match(markdown, /## 2\.X/);
  assert.doesNotMatch(markdown, /## Future/);
  assert.match(markdown, /Needs decision/);
  assert.match(markdown, /Sponsor: Sundsvall/);
  assert.match(markdown, /Owner: Team Platform/);

  const mermaid = renderOutput([], {
    owner: "eneo-ai",
    project: "5",
    format: "mermaid",
    audience: "default",
    versions: parseVersionList("2.7,Future"),
  });
  assert.match(mermaid, /version_2_7\["2\.7"\]/);
  assert.match(mermaid, /version_2_x\["2\.X"\]/);

  const futureSvg = renderOutput(epics, {
    owner: "eneo-ai",
    project: "5",
    format: "svg",
    audience: "committee",
    versions: parseVersionList("2.7,Future"),
  });
  assert.match(futureSvg, /fill="#315f7a">Owner: Search</);
  assert.match(futureSvg, />Sundsvall</);
  assert.doesNotMatch(futureSvg, /Sundsvalls kom/);
  assert.match(futureSvg, />!<\/text>/, "committee SVG should show attention icon when decisions are needed");

  const manyEpics = Array.from({ length: 12 }, (_, index) => ({
    id: `many-${index}`,
    number: 300 + index,
    title: `Overflow epic ${index + 1}`,
    status: "Todo",
    priority: "",
    area: "",
    sponsor: "",
    owner: "",
    startDate: "",
    targetDate: "",
    decisionNeeded: "",
    progress: "",
    version: "2.7",
  }));
  const svg = renderOutput(manyEpics, {
    owner: "eneo-ai",
    project: "5",
    format: "svg",
    audience: "committee",
    versions: parseVersionList("2.7,Future"),
  });

  assert.match(svg, /<svg/);
  assert.match(svg, />2\.7</);
  assert.match(svg, />2\.X</);
  assert.match(svg, /\+3 more/);
  assert.match(svg, /fill="#00879C"/, "SVG should embed the real Eneo logo asset");
  assert.doesNotMatch(svg, /fill="#c7ded1"/, "first dynamic column must not be styled as done");
  assert.doesNotMatch(svg, />!<\/text>/, "SVG without decisions should not show an attention icon");

  console.log("roadmap export self-test passed");
}

function parseArgs(argv) {
  const parsed = {};

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (!arg.startsWith("--")) {
      continue;
    }

    const key = arg.slice(2);
    const next = argv[index + 1];

    if (!next || next.startsWith("--")) {
      parsed[key] = "true";
      continue;
    }

    parsed[key] = next;
    index += 1;
  }

  return parsed;
}
