import type {
  AssistantSkillBindingInput,
  AssistantSkillConfiguration,
  SkillSparse
} from "@eneo/eneo-js";
import { SvelteMap } from "svelte/reactivity";
import { getErrorMessage } from "$lib/core/errors";
import {
  fromSavedBindings,
  personalSkillBindings,
  personalSkillRows,
  personalSkillsSaveErrorMessage,
  withLatestPersonalSkillRevision,
  withPersonalSkillMode,
  type OwnSkillRow,
  type PersonalSkillMode
} from "./personalChatSkills";
import { emptySkillCatalogPage, type ListSkills } from "./skillCatalog";
import { SkillCatalogQuery } from "./skillCatalogQuery.svelte";

type Bindings = AssistantSkillBindingInput[];

/** One choice the person made, applied to whatever is saved when its turn comes. */
type Change = {
  skillId: string;
  attempt: number;
  apply: (bindings: Bindings) => Bindings;
};

type Sources = {
  /** Reads what the server holds now. */
  readConfiguration: () => Promise<AssistantSkillConfiguration>;
  /** One page of the person's library, searched on the server. */
  listLibrary: ListSkills;
  /** Queues a save; `bindings` builds the full ordered list when its turn comes. */
  save: (bindings: () => Promise<Bindings>) => Promise<void>;
  /** Settles once every queued default-assistant update has. */
  settled: () => Promise<void>;
};

/**
 * The personal chat's Skills as the composer shows them: the saved
 * configuration with the person's pending changes applied, and the library.
 * Each change is saved on its own, applied to what the server holds when its
 * turn comes, so a refused change rolls back alone and is explained under
 * its own Skill, and never travels with a later one.
 */
export class PersonalChatSkills {
  configuration = $state<AssistantSkillConfiguration | null>(null);
  /** Paged and searched on the server; only read for a person who may choose. */
  readonly library: SkillCatalogQuery<SkillSparse>;
  /** Whether a first library page has been read. */
  libraryLoaded = $state(false);
  loadError = $state<string | null>(null);
  /** Why a change was refused, per Skill. */
  saveErrors = new SvelteMap<string, string>();
  #pending = $state.raw<Change[]>([]);
  #sources: Sources;
  #configurationReads = 0;
  #attempts = 0;
  // The latest change per Skill: only its refusal is still news.
  #latestAttempt: Record<string, number> = {};

  /** Whether the person may choose their own Skills. */
  readonly canEdit: boolean;

  constructor(sources: Sources, canEdit: boolean) {
    this.#sources = sources;
    this.canEdit = canEdit;
    this.library = new SkillCatalogQuery(emptySkillCatalogPage(), sources.listLibrary);
  }

  /** The saved bindings with the pending changes applied, in order. */
  get bindings(): Bindings {
    return this.#pending.reduce(
      (bindings, change) => change.apply(bindings),
      personalSkillBindings(this.configuration?.bindings ?? [])
    );
  }

  ownRows: OwnSkillRow[] = $derived.by(() =>
    personalSkillRows(this.configuration?.bindings ?? [], this.library.items, this.bindings, {
      searching: this.library.query.trim() !== ""
    })
  );

  /** Reads the configuration, and the library's first page when the person may choose. */
  async load({ library = false } = {}): Promise<void> {
    this.loadError = null;
    await Promise.all([
      // After queued model and Skill saves, so it describes the next turn.
      this.#sources.settled().then(() => this.#readConfiguration()),
      library && this.canEdit ? this.#loadLibrary() : undefined
    ]);
  }

  setMode(row: OwnSkillRow, mode: PersonalSkillMode): void {
    if (mode === row.mode) return;
    void this.#save(row.id, (bindings) => withPersonalSkillMode(bindings, row, mode));
  }

  useLatestRevision(row: OwnSkillRow): void {
    const binding = row.binding;
    if (!binding || !row.hasNewerRevision) return;
    void this.#save(row.id, (bindings) => withLatestPersonalSkillRevision(bindings, binding));
  }

  dispose(): void {
    this.library.dispose();
  }

  async #loadLibrary(): Promise<void> {
    // Each opening starts from the first page, unsearched.
    if (this.library.query) this.library.reset(emptySkillCatalogPage());
    await this.library.reload();
    this.libraryLoaded = true;
  }

  async #save(skillId: string, apply: Change["apply"]): Promise<void> {
    const change = { skillId, attempt: ++this.#attempts, apply };
    this.#latestAttempt[skillId] = change.attempt;
    this.#pending = [...this.#pending, change];
    this.saveErrors.delete(skillId);
    let failure: unknown = null;
    try {
      await this.#sources.save(fromSavedBindings(this.#sources.readConfiguration, apply));
    } catch (error) {
      failure = error;
    }
    // Show the outcome from the server before the change stops showing.
    await this.#readConfiguration();
    this.#pending = this.#pending.filter((pending) => pending !== change);
    // A later choice for the same Skill decides what is shown under it.
    if (failure !== null && this.#latestAttempt[skillId] === change.attempt) {
      this.saveErrors.set(skillId, personalSkillsSaveErrorMessage(failure));
    }
  }

  async #readConfiguration(): Promise<void> {
    const read = ++this.#configurationReads;
    try {
      const configuration = await this.#sources.readConfiguration();
      if (read === this.#configurationReads) this.configuration = configuration;
    } catch (error) {
      if (read === this.#configurationReads) this.loadError = getErrorMessage(error);
    }
  }
}
