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
}
