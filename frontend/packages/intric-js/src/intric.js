import { createClient } from "./client/client";
import { initAnalytics } from "./endpoints/analysis";
import { initAssistants } from "./endpoints/assistants";
import { initAuth } from "./endpoints/auth";
import { initDashboard } from "./endpoints/dashboard";
import { initFiles } from "./endpoints/files";
import { initGroups } from "./endpoints/groups";
import { initInfoBlobs } from "./endpoints/info-blobs";
import { initJobs } from "./endpoints/jobs";
import { initLimits } from "./endpoints/limits";
import { initLogging } from "./endpoints/logging";
import { initModels } from "./endpoints/models";
import { initRoles } from "./endpoints/roles";
import { initServices } from "./endpoints/services";
import { initSpaces } from "./endpoints/spaces";
import { initUserGroups } from "./endpoints/user-groups";
import { initUser } from "./endpoints/users";
import { initVersion } from "./endpoints/version";
import { initWebsites } from "./endpoints/websites";
import { initPrompts } from "./endpoints/prompts";
import { initApps } from "./endpoints/apps";
import { initTemplates } from "./endpoints/templates";
import { initUsage } from "./endpoints/usage";
import { initGroupChats } from "./endpoints/group-chats";
import { initIntegrations } from "./endpoints/integrations";
import { initConversations } from "./endpoints/conversations";
import { initSecurityClassifications } from "./endpoints/security-classifications";
import { initSettings } from "./endpoints/settings";
import { initCredentials } from "./endpoints/credentials";

/**
 * Create an Intric.js object to interact with the intric backend.
 * Requires either an api key or a user token to authenticate requests.
 * @param {Object} args
 * @param  {string} [args.apiKey] Intric API key
 * @param  {string} [args.token] Intric auth token obtained through logging in
 * @param  {string} args.baseUrl Base URL of the Intric backend
 * @param {(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>} [args.fetch] Alternative fetch function to use, defaults to native fetch
 */
export function createIntric(args) {
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
    settings: initSettings(client),
    credentials: initCredentials(client),
    client
  };
}
