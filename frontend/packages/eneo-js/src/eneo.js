import { createClient } from "./client/client.js";
import { initAnalytics } from "./endpoints/analysis.js";
import { initAssistants } from "./endpoints/assistants.js";
import { initAuth } from "./endpoints/auth.js";
import { initDashboard } from "./endpoints/dashboard.js";
import { initFiles } from "./endpoints/files.js";
import { initGroups } from "./endpoints/groups.js";
import { initInfoBlobs } from "./endpoints/info-blobs.js";
import { initJobs } from "./endpoints/jobs.js";
import { initLimits } from "./endpoints/limits.js";
import { initLogging } from "./endpoints/logging.js";
import { initModels } from "./endpoints/models.js";
import { initRoles } from "./endpoints/roles.js";
import { initServices } from "./endpoints/services.js";
import { initSpaces } from "./endpoints/spaces.js";
import { initUserGroups } from "./endpoints/user-groups.js";
import { initUser } from "./endpoints/users.js";
import { initVersion } from "./endpoints/version.js";
import { initWebsites } from "./endpoints/websites.js";
import { initPrompts } from "./endpoints/prompts.js";
import { initApps } from "./endpoints/apps.js";
import { initTemplates } from "./endpoints/templates.js";
import { initUsage } from "./endpoints/usage.js";
import { initGroupChats } from "./endpoints/group-chats.js";
import { initIntegrations } from "./endpoints/integrations.js";
import { initConversations } from "./endpoints/conversations.js";
import { initSecurityClassifications } from "./endpoints/security-classifications.js";
import { initMCPServers } from "./endpoints/mcp-servers.js";
import { initPromptLibrary } from "./endpoints/prompt-library.js";
import { initGovernancePolicy } from "./endpoints/governance-policy.js";
import { initSettings } from "./endpoints/settings.js";
import { initCredentials } from "./endpoints/credentials.js";
import { initAudit } from "./endpoints/audit.js";
import { initIcons } from "./endpoints/icons.js";
import { initModelProviders } from "./endpoints/model-providers.js";
import { initTenantModels } from "./endpoints/tenant-models.js";
import { initApiKeys } from "./endpoints/api-keys.js";
import { initHelpAssistants } from "./endpoints/helpAssistants.js";

/**
 * Create an Eneo.js object to interact with the eneo backend.
 * Requires either an api key or a user token to authenticate requests.
 * @param {Object} args
 * @param  {string} [args.apiKey] Eneo API key
 * @param  {string} [args.token] Eneo auth token obtained through logging in
 * @param  {string} args.baseUrl Base URL of the Eneo backend
 * @param {(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>} [args.fetch] Alternative fetch function to use, defaults to native fetch
 */
export function createEneo(args) {
  const client = createClient(args);
  return {
    apps: initApps(client),
    auth: initAuth(client),
    groups: initGroups(client),
    users: initUser(client),
    userGroups: initUserGroups(client),
    infoBlobs: initInfoBlobs(client),
    assistants: initAssistants(client),
    services: initServices(client),
    version: initVersion(client),
    analytics: initAnalytics(client),
    logging: initLogging(client),
    jobs: initJobs(client),
    roles: initRoles(client),
    files: initFiles(client),
    models: initModels(client),
    limits: initLimits(client),
    websites: initWebsites(client),
    spaces: initSpaces(client),
    dashboard: initDashboard(client),
    prompts: initPrompts(client),
    templates: initTemplates(client),
    usage: initUsage(client),
    groupChats: initGroupChats(client),
    integrations: initIntegrations(client),
    conversations: initConversations(client),
    securityClassifications: initSecurityClassifications(client),
    mcpServers: initMCPServers(client),
    promptLibrary: initPromptLibrary(client),
    governancePolicy: initGovernancePolicy(client),
    settings: initSettings(client),
    credentials: initCredentials(client),
    audit: initAudit(client),
    icons: initIcons(client),
    modelProviders: initModelProviders(client),
    tenantModels: initTenantModels(client),
    apiKeys: initApiKeys(client),
    helpAssistants: initHelpAssistants(client),
    client
  };
}
