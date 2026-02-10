"""Action metadata registry - Swedish names and descriptions for all 65 actions.

Used by the audit configuration UI to display human-readable action names.
"""

from intric.audit.domain.action_types import ActionType

# Maps action type values to Swedish display metadata
ACTION_METADATA = {
    # Admin Actions (13)
    ActionType.USER_CREATED.value: {
        "name_sv": "Användare skapad",
        "description_sv": "Loggar när en ny användare skapas",
    },
    ActionType.USER_DELETED.value: {
        "name_sv": "Användare raderad",
        "description_sv": "Loggar när en användare tas bort",
    },
    ActionType.USER_UPDATED.value: {
        "name_sv": "Användare uppdaterad",
        "description_sv": "Loggar ändringar av användaruppgifter",
    },
    ActionType.ROLE_CREATED.value: {
        "name_sv": "Roll skapad",
        "description_sv": "Loggar när en ny roll skapas",
    },
    ActionType.ROLE_MODIFIED.value: {
        "name_sv": "Roll ändrad",
        "description_sv": "Loggar ändringar av rollbehörigheter",
    },
    ActionType.ROLE_DELETED.value: {
        "name_sv": "Roll raderad",
        "description_sv": "Loggar när en roll tas bort",
    },
    ActionType.PERMISSION_CHANGED.value: {
        "name_sv": "Behörighet ändrad",
        "description_sv": "Loggar ändringar av användarbehörigheter",
    },
    ActionType.TENANT_SETTINGS_UPDATED.value: {
        "name_sv": "Organisationsinställningar uppdaterade",
        "description_sv": "Loggar ändringar av organisationskonfiguration",
    },
    ActionType.CREDENTIALS_UPDATED.value: {
        "name_sv": "Inloggningsuppgifter uppdaterade",
        "description_sv": "Loggar ändringar av API-credentials",
    },
    ActionType.FEDERATION_UPDATED.value: {
        "name_sv": "Federation uppdaterad",
        "description_sv": "Loggar ändringar av federationsinställningar",
    },
    ActionType.API_KEY_GENERATED.value: {
        "name_sv": "API-nyckel genererad",
        "description_sv": "Loggar när nya API-nycklar skapas",
    },
    ActionType.API_KEY_CREATED.value: {
        "name_sv": "API-nyckel skapad",
        "description_sv": "Loggar när en API-nyckel skapas",
    },
    ActionType.API_KEY_UPDATED.value: {
        "name_sv": "API-nyckel uppdaterad",
        "description_sv": "Loggar när en API-nyckel uppdateras",
    },
    ActionType.API_KEY_REVOKED.value: {
        "name_sv": "API-nyckel revokerad",
        "description_sv": "Loggar när en API-nyckel revokeras",
    },
    ActionType.API_KEY_SUSPENDED.value: {
        "name_sv": "API-nyckel pausad",
        "description_sv": "Loggar när en API-nyckel suspenderas",
    },
    ActionType.API_KEY_REACTIVATED.value: {
        "name_sv": "API-nyckel återaktiverad",
        "description_sv": "Loggar när en API-nyckel återaktiveras",
    },
    ActionType.API_KEY_ROTATED.value: {
        "name_sv": "API-nyckel roterad",
        "description_sv": "Loggar när en API-nyckel roteras",
    },
    ActionType.API_KEY_EXPIRED.value: {
        "name_sv": "API-nyckel utgången",
        "description_sv": "Loggar när en API-nyckel löper ut",
    },
    ActionType.API_KEY_USED.value: {
        "name_sv": "API-nyckel använd",
        "description_sv": "Loggar när en API-nyckel används",
    },
    ActionType.API_KEY_AUTH_FAILED.value: {
        "name_sv": "API-nyckel misslyckad",
        "description_sv": "Loggar misslyckade API-nyckelautentiseringar",
    },
    ActionType.TENANT_POLICY_UPDATED.value: {
        "name_sv": "API-nyckelpolicy uppdaterad",
        "description_sv": "Loggar ändringar av API-nyckelpolicy per tenant",
    },
    ActionType.MODULE_ADDED.value: {
        "name_sv": "Modul tillagd",
        "description_sv": "Loggar när en ny modul läggs till",
    },
    ActionType.MODULE_ADDED_TO_TENANT.value: {
        "name_sv": "Modul aktiverad",
        "description_sv": "Loggar när en modul aktiveras för organisationen",
    },
    # User Actions (41) - Assistants, Spaces, Apps, Files, etc.
    ActionType.ASSISTANT_CREATED.value: {
        "name_sv": "Assistent skapad",
        "description_sv": "Loggar när en ny assistent skapas",
    },
    ActionType.ASSISTANT_DELETED.value: {
        "name_sv": "Assistent raderad",
        "description_sv": "Loggar när en assistent tas bort",
    },
    ActionType.ASSISTANT_UPDATED.value: {
        "name_sv": "Assistent uppdaterad",
        "description_sv": "Loggar ändringar av assistentinställningar",
    },
    ActionType.ASSISTANT_TRANSFERRED.value: {
        "name_sv": "Assistent överförd",
        "description_sv": "Loggar när en assistent flyttas mellan Spaces",
    },
    ActionType.ASSISTANT_PUBLISHED.value: {
        "name_sv": "Assistent publicerad",
        "description_sv": "Loggar när en assistent publiceras",
    },
    ActionType.SPACE_CREATED.value: {
        "name_sv": "Space skapad",
        "description_sv": "Loggar när ett nytt Space skapas",
    },
    ActionType.SPACE_UPDATED.value: {
        "name_sv": "Space uppdaterad",
        "description_sv": "Loggar ändringar av Space-inställningar",
    },
    ActionType.SPACE_DELETED.value: {
        "name_sv": "Space raderad",
        "description_sv": "Loggar när ett Space tas bort",
    },
    ActionType.SPACE_MEMBER_ADDED.value: {
        "name_sv": "Medlem tillagd i Space",
        "description_sv": "Loggar när en användare läggs till i ett Space",
    },
    ActionType.SPACE_MEMBER_REMOVED.value: {
        "name_sv": "Medlem borttagen från Space",
        "description_sv": "Loggar när en användare tas bort från ett Space",
    },
    ActionType.APP_CREATED.value: {
        "name_sv": "App skapad",
        "description_sv": "Loggar när en ny app skapas",
    },
    ActionType.APP_DELETED.value: {
        "name_sv": "App raderad",
        "description_sv": "Loggar när en app tas bort",
    },
    ActionType.APP_UPDATED.value: {
        "name_sv": "App uppdaterad",
        "description_sv": "Loggar ändringar av app-inställningar",
    },
    ActionType.APP_EXECUTED.value: {
        "name_sv": "App kördes",
        "description_sv": "Loggar när en app exekveras",
    },
    ActionType.APP_PUBLISHED.value: {
        "name_sv": "App publicerad",
        "description_sv": "Loggar när en app publiceras",
    },
    ActionType.APP_RUN_DELETED.value: {
        "name_sv": "App-körning raderad",
        "description_sv": "Loggar när en app-körning tas bort",
    },
    ActionType.SESSION_STARTED.value: {
        "name_sv": "Session startad",
        "description_sv": "Loggar när en användarsession startas",
    },
    ActionType.SESSION_ENDED.value: {
        "name_sv": "Session avslutad",
        "description_sv": "Loggar när en användarsession avslutas",
    },
    ActionType.FILE_UPLOADED.value: {
        "name_sv": "Fil uppladdad",
        "description_sv": "Loggar när filer laddas upp",
    },
    ActionType.FILE_DELETED.value: {
        "name_sv": "Fil raderad",
        "description_sv": "Loggar när filer tas bort",
    },
    ActionType.WEBSITE_CREATED.value: {
        "name_sv": "Webbplats tillagd",
        "description_sv": "Loggar när en webbplats läggs till för crawling",
    },
    ActionType.WEBSITE_UPDATED.value: {
        "name_sv": "Webbplats uppdaterad",
        "description_sv": "Loggar ändringar av webbplatsinställningar",
    },
    ActionType.WEBSITE_DELETED.value: {
        "name_sv": "Webbplats borttagen",
        "description_sv": "Loggar när en webbplats tas bort",
    },
    ActionType.WEBSITE_CRAWLED.value: {
        "name_sv": "Webbplats crawlad",
        "description_sv": "Loggar när en webbplats crawlas",
    },
    ActionType.WEBSITE_TRANSFERRED.value: {
        "name_sv": "Webbplats överförd",
        "description_sv": "Loggar när en webbplats flyttas mellan Spaces",
    },
    ActionType.GROUP_CHAT_CREATED.value: {
        "name_sv": "Gruppchatt skapad",
        "description_sv": "Loggar när en ny gruppchatt skapas",
    },
    ActionType.COLLECTION_CREATED.value: {
        "name_sv": "Samling skapad",
        "description_sv": "Loggar när en ny samling skapas",
    },
    ActionType.COLLECTION_UPDATED.value: {
        "name_sv": "Samling uppdaterad",
        "description_sv": "Loggar ändringar av samlingar",
    },
    ActionType.COLLECTION_DELETED.value: {
        "name_sv": "Samling raderad",
        "description_sv": "Loggar när en samling tas bort",
    },
    ActionType.INTEGRATION_ADDED.value: {
        "name_sv": "Integration tillagd",
        "description_sv": "Loggar när en ny integration läggs till",
    },
    ActionType.INTEGRATION_REMOVED.value: {
        "name_sv": "Integration borttagen",
        "description_sv": "Loggar när en integration tas bort",
    },
    ActionType.INTEGRATION_CONNECTED.value: {
        "name_sv": "Integration ansluten",
        "description_sv": "Loggar när en integration kopplas upp",
    },
    ActionType.INTEGRATION_DISCONNECTED.value: {
        "name_sv": "Integration frånkopplad",
        "description_sv": "Loggar när en integration kopplas ner",
    },
    ActionType.INTEGRATION_KNOWLEDGE_CREATED.value: {
        "name_sv": "Integrationskälla skapad",
        "description_sv": "Loggar när en kunskapskälla från integration skapas",
    },
    ActionType.INTEGRATION_KNOWLEDGE_DELETED.value: {
        "name_sv": "Integrationskälla raderad",
        "description_sv": "Loggar när en kunskapskälla tas bort",
    },
    ActionType.INTEGRATION_KNOWLEDGE_SYNCED.value: {
        "name_sv": "Integrationskälla synkad",
        "description_sv": "Loggar när en full synkning startas för en integrationskälla",
    },
    ActionType.COMPLETION_MODEL_UPDATED.value: {
        "name_sv": "Kompletteringsmodell uppdaterad",
        "description_sv": "Loggar ändringar av AI-kompletteringsmodell",
    },
    ActionType.EMBEDDING_MODEL_UPDATED.value: {
        "name_sv": "Embedding-modell uppdaterad",
        "description_sv": "Loggar ändringar av embedding-modell",
    },
    ActionType.TRANSCRIPTION_MODEL_UPDATED.value: {
        "name_sv": "Transkriptionsmodell uppdaterad",
        "description_sv": "Loggar ändringar av transkriptionsmodell",
    },
    ActionType.TEMPLATE_CREATED.value: {
        "name_sv": "Mall skapad",
        "description_sv": "Loggar när en ny mall skapas",
    },
    ActionType.TEMPLATE_UPDATED.value: {
        "name_sv": "Mall uppdaterad",
        "description_sv": "Loggar ändringar av mallar",
    },
    ActionType.TEMPLATE_DELETED.value: {
        "name_sv": "Mall raderad",
        "description_sv": "Loggar när en mall tas bort",
    },
    # Security Events (6)
    ActionType.SECURITY_CLASSIFICATION_CREATED.value: {
        "name_sv": "Säkerhetsklassificering skapad",
        "description_sv": "Loggar när en säkerhetsklassificering skapas",
    },
    ActionType.SECURITY_CLASSIFICATION_UPDATED.value: {
        "name_sv": "Säkerhetsklassificering uppdaterad",
        "description_sv": "Loggar ändringar av säkerhetsklassificeringar",
    },
    ActionType.SECURITY_CLASSIFICATION_DELETED.value: {
        "name_sv": "Säkerhetsklassificering raderad",
        "description_sv": "Loggar när en säkerhetsklassificering tas bort",
    },
    ActionType.SECURITY_CLASSIFICATION_LEVELS_UPDATED.value: {
        "name_sv": "Säkerhetsnivåer uppdaterade",
        "description_sv": "Loggar ändringar av säkerhetsnivåer",
    },
    ActionType.SECURITY_CLASSIFICATION_ENABLED.value: {
        "name_sv": "Säkerhetsklassificering aktiverad",
        "description_sv": "Loggar när säkerhetsklassificering aktiveras",
    },
    ActionType.SECURITY_CLASSIFICATION_DISABLED.value: {
        "name_sv": "Säkerhetsklassificering inaktiverad",
        "description_sv": "Loggar när säkerhetsklassificering inaktiveras",
    },
    # System Actions (3)
    ActionType.RETENTION_POLICY_APPLIED.value: {
        "name_sv": "Retentionspolicy tillämpades",
        "description_sv": "Loggar när gamla granskningsloggar rensas",
    },
    ActionType.ENCRYPTION_KEY_ROTATED.value: {
        "name_sv": "Krypteringsnyckel roterad",
        "description_sv": "Loggar rotation av krypteringsnycklar",
    },
    ActionType.SYSTEM_MAINTENANCE.value: {
        "name_sv": "Systemunderhåll",
        "description_sv": "Loggar planerat systemunderhåll",
    },
    # Audit Access (2)
    ActionType.AUDIT_LOG_VIEWED.value: {
        "name_sv": "Granskningsloggar visade",
        "description_sv": "Loggar när granskningsloggar visas",
    },
    ActionType.AUDIT_LOG_EXPORTED.value: {
        "name_sv": "Granskningsloggar exporterade",
        "description_sv": "Loggar när granskningsloggar exporteras",
    },
}


def get_action_metadata(action: str) -> dict:
    """Get Swedish metadata for an action.

    Args:
        action: Action type value (e.g., "user_created")

    Returns:
        Dict with name_sv and description_sv
    """
    return ACTION_METADATA.get(
        action,
        {
            "name_sv": action.replace("_", " ").title(),
            "description_sv": f"Loggar {action.replace('_', ' ')}",
        },
    )


def get_all_actions() -> list[str]:
    """Return all registered action type values."""
    return list(ACTION_METADATA.keys())
