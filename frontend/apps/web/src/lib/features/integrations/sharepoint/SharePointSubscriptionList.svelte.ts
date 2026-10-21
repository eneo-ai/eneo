import type { Eneo, components } from "@eneo/eneo-js";

type SharePointSubscription = components["schemas"]["SharePointSubscriptionPublic"];

/**
 * The tenant's SharePoint subscriptions, shared by the views of the admin page so
 * that renewing in one updates the counts and actions of the other.
 */
export class SharePointSubscriptionList {
  /** Null before the first load and after a failed one. */
  items = $state<SharePointSubscription[] | null>(null);
  loading = $state(false);

  #eneo: Eneo;
  #generation = 0;

  constructor(eneo: Eneo) {
    this.#eneo = eneo;
  }

  /** Rejects when the list could not be loaded. */
  async load(): Promise<void> {
    const generation = ++this.#generation;
    this.loading = true;
    try {
      const response = await this.#eneo.integrations.admin.sharepoint.listSubscriptions();
      if (generation === this.#generation) this.items = Array.isArray(response) ? response : [];
    } catch (error) {
      if (generation === this.#generation) this.items = null;
      throw error;
    } finally {
      if (generation === this.#generation) this.loading = false;
    }
  }
}
