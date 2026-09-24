import type { PageMapItem } from "nextra";
import { type DocsLanguage, languagePath } from "./languages";

const swedishTitles: Readonly<Record<string, string>> = {
  "/": "Start",
  "/docs": "Dokumentation",
  "/guides": "Guider",
  "/contributing": "Bidra",
  "/about": "Om Eneo",
  "/docs/getting-started": "Kom igång",
  "/docs/architecture": "Arkitektur",
  "/docs/authentication-architecture": "Autentiseringens arkitektur",
  "/docs/module-authentication": "Inloggning i moduler",
  "/docs/knowledge-retrieval-and-mcp": "Kunskapssökning och MCP",
  "/docs/builtin-tool-servers": "Inbyggda verktygsservrar",
  "/docs/object-content-architecture": "Lagringsarkitektur",
  "/docs/audit-logging": "Granskningsloggning",
  "/docs/api-key-management": "Hantera API-nycklar",
  "/docs/release-sboms": "Programvaruförteckningar (SBOM)",
  "/docs/token-counting": "Tokenräkning",
  "/docs/api": "API-referens",
  "/guides/oidc-federation": "Autentisering och OIDC",
  "/guides/oidc-federation/single-tenant": "En organisation",
  "/guides/oidc-federation/multi-tenant": "Federation för flera organisationer",
  "/guides/scim-provisioning": "Provisionering med SCIM",
  "/guides/audit-logging": "Granskningsloggning",
  "/guides/space-oversight": "Tillsyn över ytor",
  "/guides/skills": "Färdigheter",
  "/guides/ai-providers": "Konfigurera AI-leverantörer",
  "/guides/mcp-servers": "MCP-servrar",
  "/guides/capabilities": "Webbsökning och bildgenerering",
  "/guides/deployment": "Driftsätt Eneo",
  "/guides/embed-widget": "Bädda in en chattwidget",
  "/guides/file-icon-storage-upgrade": "Uppgradera fil- och ikonlagring",
  "/guides/object-content-storage": "Välj innehållslagring",
  "/guides/document-processing": "Dokumentbearbetning",
  "/guides/sharepoint-integration": "SharePoint-integration",
  "/guides/upgrade-1-7-0": "Uppgradera till 1.7.0",
  "/contributing/project-roadmap": "Projektets planering",
  "/contributing/security": "Säkerhet",
  "/about/release-notes": "Versionsnyheter",
};

// Preserve the selected ref's inventory, metadata and ordering. Only titles
// and routes change; current navigation must never add pages to an older ref.
export function languagePageMap(
  items: PageMapItem[],
  language: DocsLanguage,
  parent = "",
): PageMapItem[] {
  return items
    .filter((item) => !("name" in item && item.name === "sv" && !parent))
    .map((item) => {
      if ("data" in item) {
        const data = Object.fromEntries(
          Object.entries(item.data)
            .filter(([name]) => parent || name !== "sv")
            .map(([name, meta]) => {
              const route =
                name === "index" ? parent || "/" : `${parent}/${name}`;
              const title =
                name === "index" && parent ? "Översikt" : swedishTitles[route];
              return [
                name,
                language === "sv" && title
                  ? typeof meta === "string"
                    ? title
                    : { ...meta, title }
                  : meta,
              ];
            }),
        );
        return { ...item, data };
      }
      const route = languagePath(item.route, language);
      if ("children" in item)
        return {
          ...item,
          route,
          children: languagePageMap(item.children, language, item.route),
        };
      return {
        ...item,
        route,
        ...(language === "sv" && swedishTitles[item.route]
          ? {
              frontMatter: {
                ...item.frontMatter,
                title: swedishTitles[item.route],
              },
            }
          : {}),
      };
    });
}
