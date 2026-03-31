# MIT License

# flake8: noqa
from intric.roles.permissions import Permission

PERMISSIONS_WITH_DESCRIPTION = {
    Permission.ASSISTANTS: "Management of Assistants. Create, Update, and Delete Assistants.",
    Permission.GROUP_CHATS: "Management of Group Chats. Create, Update, and Delete Assistants.",
    Permission.APPS: "Management of Apps. Create, Update, and Delete Apps",
    Permission.SERVICES: "Management of Services. Create, Update, and Delete Services.",
    Permission.COLLECTIONS: "Management of Collections. Create, Update, and Delete Collections.",
    Permission.WEBSITES: "Management of Websites. Create, Update, and Delete Websites",
    Permission.INSIGHTS: "See Insights about your Organization.",
    Permission.INTEGRATIONS: "Management of Integrations. Create, Update, and Delete Integration Knowledge.",
    Permission.AI: "More in-depth AI configuration.",
    Permission.ADMIN: "Organization owner. Management of Users, Roles, and Groups.",
    Permission.FLOWS: "Legacy full-access Flow permission. Grants flow view, run, manage, and AI Builder access.",
    Permission.FLOWS_VIEW: "View flow definitions, published flow structure, and flow run details.",
    Permission.FLOWS_RUN: "Run published flows, upload runtime inputs, and manage flow runs.",
    Permission.FLOWS_MANAGE: "Create, update, publish, and delete flows and flow-managed resources.",
    Permission.FLOWS_AI_BUILDER: "Use the AI Builder to plan and edit flows.",
    Permission.FLOWS_TRACE: "Inspect and export rich flow evidence, provenance, and AI Builder trace data.",
}
