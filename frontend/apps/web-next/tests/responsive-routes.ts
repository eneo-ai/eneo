/**
 * Every route of the app, and how the responsive contract
 * (tests/responsive-contract.spec.ts) reaches it. The keys are the route
 * patterns of the generated route tree (`$` for a parameter, `*` for a
 * splat); src/test/responsive-routes.test.ts fails when a route is missing
 * here, so a new screen cannot ship without a decision: how to open it, or
 * why the contract does not (a `skip` with its reason).
 *
 * A skip is a debt, not a verdict. SKIP_BUDGET only goes down.
 */

/** What the contract creates once and routes can point at. */
export type Fixtures = {
  /** `/spaces/<id>`: a shared space. */
  space: string;
  spaceName: string;
  assistant: string;
  app: string;
  run: string;
  groupChat: string;
  groupChatName: string;
  website: string;
  collection: string;
  /** The signed-in user, who has token usage to show. */
  userId: string;
  widgetTemplate: string;
};

export type Entry = { url: (f: Fixtures) => string; auth?: "in" | "out" } | { skip: string };

const open = (path: string): Entry => ({ url: () => path });
const closed = (path: string): Entry => ({ url: () => path, auth: "out" });

export const ROUTES: Record<string, Entry> = {
  "/": { skip: "Redirects to the start page; the page it lands on is covered." },
  "/*": open("/nothing-here-at-all"),
  "/account": open("/account"),
  "/account/api-keys": open("/account/api-keys"),
  "/account/appearance": open("/account/appearance"),
  "/account/copy-format": open("/account/copy-format"),
  "/account/integrations": open("/account/integrations"),
  "/account/password": open("/account/password"),
  "/admin": open("/admin"),
  "/admin/api-keys": open("/admin/api-keys"),
  "/admin/audit-logs": {
    skip: "Each visit opens one of five audit access sessions an hour (tests/helpers.ts auditLogs); tests/a11y.spec.ts scans it on a phone."
  },
  "/admin/crawler": open("/admin/crawler"),
  "/admin/federation": open("/admin/federation"),
  "/admin/help-assistants": open("/admin/help-assistants"),
  "/admin/help-assistants/$": { skip: "Needs a help assistant fixture." },
  "/admin/insights": open("/admin/insights"),
  "/admin/insights/assistant/$": { skip: "Needs an assistant with conversations." },
  "/admin/integrations": open("/admin/integrations"),
  "/admin/mcp-servers": open("/admin/mcp-servers"),
  "/admin/mcp-servers/$": {
    skip: "Needs an MCP server fixture: creating one connects to a live MCP server."
  },
  "/admin/models": open("/admin/models"),
  "/admin/modules": open("/admin/modules"),
  "/admin/personal-assistant": open("/admin/personal-assistant"),
  "/admin/prompt-library": open("/admin/prompt-library"),
  "/admin/roles": open("/admin/roles"),
  "/admin/security-classifications": open("/admin/security-classifications"),
  "/admin/settings": open("/admin/settings"),
  "/admin/skills": open("/admin/skills"),
  "/admin/user-groups": open("/admin/user-groups"),
  "/admin/storage": open("/admin/storage"),
  "/admin/templates": open("/admin/templates"),
  "/admin/tools": open("/admin/tools"),
  "/admin/usage": open("/admin/usage"),
  "/admin/usage/users/$": { url: (f) => `/admin/usage/users/${f.userId}` },
  "/admin/users": open("/admin/users"),
  "/admin/widgets": open("/admin/widgets"),
  "/admin/widgets/templates/$": { url: (f) => `/admin/widgets/templates/${f.widgetTemplate}` },
  "/dashboard": open("/dashboard"),
  "/dashboard/$/*": { url: (f) => `/dashboard/${f.assistant}` },
  "/dashboard/app/$": { url: (f) => `/dashboard/app/${f.app}` },
  "/dashboard/app/$/results/$": { url: (f) => `/dashboard/app/${f.app}/results/${f.run}` },
  "/deactivated": closed("/deactivated"),
  "/documents/$": open("/documents/00000000-0000-4000-8000-000000000000"),
  // Offline widgets still render the visitor notice, without an Eneo account.
  "/embed/$": closed("/embed/wgt_0000000000000000000000"),
  "/en/embed/$": closed("/en/embed/wgt_0000000000000000000000"),
  "/integrations/callback/token": closed("/integrations/callback/token"),
  "/invite/*": closed("/invite/not-a-real-invitation"),
  "/login": closed("/login?showUsernameAndPassword=true"),
  "/login/failed": closed("/login/failed?message=Fel%20vid%20inloggning"),
  "/login/switch-organisation": closed("/login/switch-organisation"),
  "/logout": { skip: "Signs the session out and redirects." },
  "/module-login": closed("/module-login"),
  "/module-login/failed": closed("/module-login/failed"),
  "/password-change": closed("/password-change"),
  "/spaces": { skip: "Redirects to the spaces list." },
  "/spaces/$": { url: (f) => f.space },
  "/spaces/$/*": { url: (f) => `${f.space}/nothing-here-at-all` },
  "/spaces/$/apps": { url: (f) => `${f.space}/apps` },
  "/spaces/$/apps/$": { url: (f) => `${f.space}/apps/${f.app}` },
  "/spaces/$/apps/$/edit": { url: (f) => `${f.space}/apps/${f.app}/edit` },
  "/spaces/$/apps/$/results/$": { url: (f) => `${f.space}/apps/${f.app}/results/${f.run}` },
  "/spaces/$/assistants": { url: (f) => `${f.space}/assistants` },
  "/spaces/$/assistants/$/edit": { url: (f) => `${f.space}/assistants/${f.assistant}/edit` },
  "/spaces/$/assistants/$/widget": { url: (f) => `${f.space}/assistants/${f.assistant}/widget` },
  "/spaces/$/chat": { url: (f) => `${f.space}/chat` },
  "/spaces/$/group-chats/$/edit": { url: (f) => `${f.space}/group-chats/${f.groupChat}/edit` },
  "/spaces/$/knowledge": { url: (f) => `${f.space}/knowledge` },
  "/spaces/$/knowledge/collections/$": {
    url: (f) => `${f.space}/knowledge/collections/${f.collection}`
  },
  "/spaces/$/knowledge/integrations": { url: (f) => `${f.space}/knowledge/integrations` },
  "/spaces/$/knowledge/integrations/$": { skip: "Needs a connected integration." },
  "/spaces/$/knowledge/integrations/wrapper/$": { skip: "Needs a connected integration." },
  "/spaces/$/knowledge/websites/$": { url: (f) => `${f.space}/knowledge/websites/${f.website}` },
  "/spaces/$/members": { url: (f) => `${f.space}/members` },
  "/spaces/$/overview": { url: (f) => `${f.space}/overview` },
  "/spaces/$/settings": { url: (f) => `${f.space}/settings` },
  "/spaces/$/skills": { url: (f) => `${f.space}/skills` },
  "/spaces/$/skills/$": { skip: "Needs a skill fixture." },
  "/spaces/$/skills/new": { url: (f) => `${f.space}/skills/new` },
  "/spaces/list": open("/spaces/list"),
  "/whats-new": open("/whats-new")
};

/** Routes the contract does not open yet. Lower it when a fixture lands; never raise it. */
export const SKIP_BUDGET = 11;

export const skipped = () => Object.entries(ROUTES).filter(([, entry]) => "skip" in entry);
