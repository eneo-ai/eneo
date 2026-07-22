import { getErrorMessage } from "$lib/core/errors";
import {
  SKILL_CATALOG_PAGE_SIZE,
  SKILL_CATALOG_SEARCH_DEBOUNCE_MS,
  mergeSkillPages,
  type ListSkills,
  type SkillCatalogPage
} from "./skillCatalog";

export class SkillCatalogQuery {
  #list: ListSkills;
  #requestId = 0;
  #debounceTimer: ReturnType<typeof setTimeout> | undefined;

  items = $state<SkillCatalogPage["items"]>([]);
  nextCursor = $state<string | null>(null);
  query = $state("");
  loading = $state(false);
  loadingMore = $state(false);
  error = $state<string | null>(null);

  constructor(initialPage: SkillCatalogPage, list: ListSkills) {
    this.#list = list;
    this.#applyPage(initialPage, false);
  }

  get hasMore(): boolean {
    return this.nextCursor !== null;
  }

  reset(page: SkillCatalogPage): void {
    clearTimeout(this.#debounceTimer);
    this.#requestId += 1;
    this.query = "";
    this.loading = false;
    this.loadingMore = false;
    this.error = null;
    this.#applyPage(page, false);
  }

  setQuery(value: string): void {
    if (value === this.query) return;

    this.query = value;
    this.#requestId += 1;
    this.loading = false;
    this.loadingMore = false;
    this.error = null;
    clearTimeout(this.#debounceTimer);
    this.#debounceTimer = setTimeout(() => {
      void this.reload();
    }, SKILL_CATALOG_SEARCH_DEBOUNCE_MS);
  }

  async reload(): Promise<void> {
    clearTimeout(this.#debounceTimer);
    await this.#load(false);
  }

  async retry(): Promise<void> {
    await this.#load(false);
  }

  async loadMore(): Promise<void> {
    if (this.nextCursor === null || this.loading || this.loadingMore) return;
    await this.#load(true);
  }

  dispose(): void {
    clearTimeout(this.#debounceTimer);
    this.#requestId += 1;
  }

  async #load(append: boolean): Promise<void> {
    const cursor = append ? this.nextCursor : null;
    if (append && cursor === null) return;

    const requestId = ++this.#requestId;
    if (append) this.loadingMore = true;
    else this.loading = true;
    this.error = null;

    try {
      const page = await this.#list({
        limit: SKILL_CATALOG_PAGE_SIZE,
        cursor,
        query: this.query.trim() || null
      });
      if (requestId !== this.#requestId) return;
      this.#applyPage(page, append);
    } catch (error) {
      if (requestId !== this.#requestId) return;
      this.error = getErrorMessage(error);
    } finally {
      if (requestId === this.#requestId) {
        this.loading = false;
        this.loadingMore = false;
      }
    }
  }

  #applyPage(page: SkillCatalogPage, append: boolean): void {
    this.items = append ? mergeSkillPages(this.items, page.items) : [...page.items];
    this.nextCursor = page.next_cursor ?? null;
  }
}
