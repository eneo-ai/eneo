import type { AdminSpaceKnowledgeSource, OversightKnowledgeRef } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

/** A knowledge source as oversight shows it: a reference, or a source with its counts. */
export type OversightKnowledge = OversightKnowledgeRef | AdminSpaceKnowledgeSource;

/**
 * The source's name, or a neutral label when the API gives none: an
 * integration source that is not a whole site is a file or a folder, whose
 * name is a document title, and a OneDrive name is personal.
 */
export function knowledgeName(
  source: Pick<OversightKnowledge, "name" | "kind" | "integration_type" | "integration_item">
): string {
  if (source.name) return source.name;
  switch (source.integration_type) {
    case "onedrive":
      return m.admin_spaces_onedrive_name();
    case "sharepoint":
      switch (source.integration_item) {
        case "file":
          return m.admin_spaces_sharepoint_file();
        case "folder":
          return m.admin_spaces_sharepoint_folder();
        default:
          return m.admin_spaces_sharepoint_item();
      }
    default:
      return knowledgeKindLabel(source);
  }
}

/** Samling, Webbplats, or the integration's product when it is known. */
export function knowledgeKindLabel(
  source: Pick<OversightKnowledgeRef, "kind"> & {
    integration_type?: AdminSpaceKnowledgeSource["integration_type"];
  }
): string {
  switch (source.kind) {
    case "collection":
      return m.admin_spaces_kind_collection();
    case "website":
      return m.admin_spaces_kind_website();
    case "integration":
      switch (source.integration_type) {
        case "sharepoint":
          return m.admin_spaces_kind_sharepoint();
        case "confluence":
          return m.admin_spaces_kind_confluence();
        case "onedrive":
          return m.admin_spaces_kind_onedrive();
        default:
          return m.admin_spaces_kind_integration();
      }
    default:
      return source.kind satisfies never;
  }
}

/** "{n} dokument", or "{n} sidor" for a website. */
export function knowledgeItemCount(
  source: Pick<AdminSpaceKnowledgeSource, "kind" | "item_count">,
  format: (value: number) => string = String
): string {
  const count = source.item_count;
  if (source.kind === "website") {
    return count === 1
      ? m.admin_spaces_knowledge_pages_one()
      : m.admin_spaces_knowledge_pages({ count: format(count) });
  }
  return count === 1
    ? m.admin_spaces_knowledge_documents_one()
    : m.admin_spaces_knowledge_documents({ count: format(count) });
}
