/** A model-list row for a linked model the model catalogue does not list.
 *
 *  It carries only what the space reports about the link, so it can be shown
 *  and switched off, never switched on; `link_only` tells it apart from a
 *  catalogue model, which also drives the status icons. */
export type LinkedModelRow = {
  link_only: true;
  id: string;
  name: string;
  nickname: string | null;
  is_org_enabled: boolean;
  meets_security_classification: boolean;
  org: null;
  provider_name: null;
  provider_type: null;
};

export function isLinkedModelRow(model: object): model is LinkedModelRow {
  return "link_only" in model && model.link_only === true;
}
