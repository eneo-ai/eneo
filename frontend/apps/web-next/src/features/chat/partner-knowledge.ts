import type { Schema } from "@/lib/api/models";
import type { KnowledgeOrigin } from "@/lib/chat/types";

type WithKnowledge = {
  groups?: Pick<Schema<"CollectionPublic">, "id" | "name">[] | null;
  websites?: Pick<Schema<"WebsitePublic">, "id" | "name" | "url">[] | null;
};

/** The collections and websites an assistant searches, for named sources and activity steps. */
export function partnerKnowledge(assistant: WithKnowledge): KnowledgeOrigin[] {
  return [
    ...(assistant.groups ?? []).map((group) => ({
      id: group.id,
      name: group.name,
      kind: "collection" as const
    })),
    ...(assistant.websites ?? []).map((website) => ({
      id: website.id,
      name: website.name?.trim() || website.url,
      kind: "website" as const
    }))
  ];
}
