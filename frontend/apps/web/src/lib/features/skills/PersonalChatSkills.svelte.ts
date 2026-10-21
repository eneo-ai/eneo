import type {
  AssistantSkillBindingInput,
  AssistantSkillConfiguration,
  SkillSparse
} from "@eneo/eneo-js";
import { SvelteMap } from "svelte/reactivity";
import { getErrorMessage } from "$lib/core/errors";
import {
  personalSkillBindings,
  personalSkillRows,
  personalSkillsSaveErrorMessage,
  withLatestPersonalSkillRevision,
  withPersonalSkillMode,
  type OwnSkillRow,
  type PersonalSkillMode
} from "./personalChatSkills";

type Bindings = AssistantSkillBindingInput[];

/** One choice the person made, applied to whatever is saved when its turn comes. */
type Change = { skillId: string; apply: (bindings: Bindings) => Bindings };

type Sources = {
  /** Reads what the server holds now. */
  readConfiguration: () => Promise<AssistantSkillConfiguration>;
  readLibrary: () => Promise<SkillSparse[]>;
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
  library = $state<SkillSparse[] | null>(null);
  loadError = $state<string | null>(null);
  /** Why a change was refused, per Skill. */
  saveErrors = new SvelteMap<string, string>();
  #pending = $state.raw<Change[]>([]);
  #sources: Sources;
  #configurationReads = 0;
  #libraryReads = 0;

  /** Whether the person may choose their own Skills. */
  readonly canEdit: boolean;

  constructor(sources: Sources, canEdit: boolean) {
    this.#sources = sources;
    this.canEdit = canEdit;
  }

  /** The saved bindings with the pending changes applied, in order. */
  get bindings(): Bindings {
    return this.#pending.reduce(
      (bindings, change) => change.apply(bindings),
      personalSkillBindings(this.configuration?.bindings ?? [])
    );
  }

  ownRows: OwnSkillRow[] = $derived(
    personalSkillRows(this.configuration?.bindings ?? [], this.library, this.bindings)
  );

  /** Reads the configuration, and the library too when the person may choose. */
  async load({ library = false } = {}): Promise<void> {
    this.loadError = null;
    await Promise.all([
      // After queued model and Skill saves, so it describes the next turn.
      this.#sources.settled().then(() => this.#readConfiguration()),
      library && this.canEdit ? this.#readLibrary() : undefined
    ]);
  }

  setMode(row: OwnSkillRow, mode: PersonalSkillMode): void {
    if (mode === row.mode) return;
    void this.#save({
      skillId: row.id,
      apply: (bindings) => withPersonalSkillMode(bindings, row, mode)
    });
  }

  useLatestRevision(row: OwnSkillRow): void {
    const binding = row.binding;
    if (!binding || !row.hasNewerRevision) return;
    void this.#save({
      skillId: row.id,
      apply: (bindings) => withLatestPersonalSkillRevision(bindings, binding)
    });
  }

  async #save(change: Change): Promise<void> {
    this.#pending = [...this.#pending, change];
    this.saveErrors.delete(change.skillId);
    let failure: unknown = null;
    try {
      await this.#sources.save(async () =>
        change.apply(personalSkillBindings((await this.#sources.readConfiguration()).bindings))
      );
    } catch (error) {
      failure = error;
    }
    // Show the outcome from the server before the change stops showing.
    await this.#readConfiguration();
    this.#pending = this.#pending.filter((pending) => pending !== change);
    if (failure !== null) {
      this.saveErrors.set(change.skillId, personalSkillsSaveErrorMessage(failure));
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

  async #readLibrary(): Promise<void> {
    const read = ++this.#libraryReads;
    try {
      const library = await this.#sources.readLibrary();
      if (read === this.#libraryReads) this.library = library;
    } catch (error) {
      if (read === this.#libraryReads) this.loadError = getErrorMessage(error);
    }
  }
}
