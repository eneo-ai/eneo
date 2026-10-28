"use client";

import { createContext, type RefObject } from "react";
import type { Collection, IntegrationKnowledge, Website } from "./knowledge";

export type KnowledgeActionSelection =
  | { kind: "collection"; collection: Collection; action: "edit" | "delete" }
  | { kind: "website"; website: Website; action: "edit" | "delete" }
  | {
      kind: "integration";
      item: IntegrationKnowledge;
      action: "rename" | "sync" | "delete";
      anchor: RefObject<HTMLSpanElement | null>;
      onDeleted?: () => void;
    }
  | {
      kind: "wrapper";
      wrapperId: string;
      wrapperName: string;
      items: IntegrationKnowledge[];
      action: "rename" | "resync" | "delete";
      anchor: RefObject<HTMLSpanElement | null>;
      onDeleted?: () => void;
    };

/** Shared by the knowledge hub; standalone action menus own their dialog locally. */
export const KnowledgeActionContext = createContext<
  ((selection: KnowledgeActionSelection) => void) | null
>(null);
