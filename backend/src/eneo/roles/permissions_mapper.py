# MIT License

# flake8: noqa
from eneo.roles.permissions import Permission

PERMISSIONS_WITH_DESCRIPTION = {
    Permission.ASSISTANTS: "Management of Assistants. Create, Update, and Delete Assistants.",
    Permission.PERSONAL_CHAT: "Use the personal chat. Without this permission the personal chat is unavailable; all other access is unaffected.",
    Permission.GROUP_CHATS: "Management of Group Chats. Create, Update, and Delete Assistants.",
    Permission.APPS: "Management of Apps. Create, Update, and Delete Apps",
    Permission.SERVICES: "Management of Services. Create, Update, and Delete Services.",
    Permission.COLLECTIONS: "Management of Collections. Create, Update, and Delete Collections.",
    Permission.WEBSITES: "Management of Websites. Create, Update, and Delete Websites",
    Permission.INSIGHTS: "See Insights about your Organization.",
    Permission.INTEGRATIONS: "Management of Integrations. Create, Update, and Delete Integration Knowledge.",
    Permission.AI: "More in-depth AI configuration.",
    Permission.ADMIN: "Organization owner. Management of Users, Roles, and Groups.",
    Permission.SHARED_SPACES: "Create shared Spaces. Viewing, editing, and deleting shared Spaces are governed by space membership.",
    Permission.API_KEYS: "Create API keys. Required for minting tenant, space, assistant, and app-scoped keys via the dashboard.",
}
