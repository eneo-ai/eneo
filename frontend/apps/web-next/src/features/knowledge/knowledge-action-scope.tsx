"use client";

import { useState, type ReactNode, type RefObject } from "react";
import { useFocusRescue } from "@/lib/focus-rescue";
import { CollectionActionDialog } from "./collections";
import { IntegrationActionDialog, WrapperActionDialog } from "./integrations/actions";
import { KnowledgeActionContext, type KnowledgeActionSelection } from "./knowledge-action-context";
import { WebsiteActionDialog } from "./websites";

/** Open edits outlive the phone/table presentation that launched them. */
export function KnowledgeActionScope({
  children,
  focusTarget
}: {
  children: ReactNode;
  focusTarget: RefObject<HTMLElement | null>;
}) {
  const [selection, setSelection] = useState<KnowledgeActionSelection | null>(null);
  const rescueFocus = useFocusRescue();
  const onClose = () => {
    rescueFocus(() => focusTarget.current);
    setSelection((current) => (current === selection ? null : current));
  };
  let dialog: ReactNode = null;
  switch (selection?.kind) {
    case "collection":
      dialog = <CollectionActionDialog {...selection} onClose={onClose} />;
      break;
    case "website":
      dialog = <WebsiteActionDialog {...selection} onClose={onClose} />;
      break;
    case "integration":
      dialog = <IntegrationActionDialog {...selection} onClose={onClose} />;
      break;
    case "wrapper":
      dialog = <WrapperActionDialog {...selection} onClose={onClose} />;
      break;
  }
  return (
    <KnowledgeActionContext value={setSelection}>
      {children}
      {dialog}
    </KnowledgeActionContext>
  );
}
