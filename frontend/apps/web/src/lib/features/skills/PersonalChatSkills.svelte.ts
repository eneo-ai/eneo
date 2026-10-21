import type {
  AssistantSkillBindingInput,
  AssistantSkillConfiguration,
  SkillSparse
} from "@eneo/eneo-js";
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

type Sources = {
  readConfiguration: () => Promise<AssistantSkillConfiguration>;
  readLibrary: () => Promise<SkillSparse[]>;
  /** Saves the full ordered list of the person's own Skills. */
  save: (bindings: AssistantSkillBindingInput[]) => Promise<void>;
};

/**
 * The personal chat's Skills as the composer shows them: the saved
 * configuration, the person's library and the change being saved. A change
 * shows at once; the configuration is read again once the last change has
 * settled, so a refused change rolls back to what the server holds.
 */
export class PersonalChatSkills {
  configuration = $state<AssistantSkillConfiguration | null>(null);
  library = $state<SkillSparse[] | null>(null);
  loadError = $state<string | null>(null);
  saveError = $state<{ skillId: string; message: string } | null>(null);
  #draft = $state<AssistantSkillBindingInput[] | null>(null);
  #sources: Sources;
  #configurationReads = 0;
  #libraryReads = 0;
  #changes = 0;

  /** Whether the person may choose their own Skills (`personal_skills`). */
  readonly canEdit: boolean;

  constructor(sources: Sources, canEdit: boolean) {
    this.#sources = sources;
    this.canEdit = canEdit;
  }

  get bindings(): AssistantSkillBindingInput[] {
    return this.#draft ?? personalSkillBindings(this.configuration?.bindings ?? []);
  }

  ownRows: OwnSkillRow[] = $derived(
    personalSkillRows(this.configuration?.bindings ?? [], this.library, this.bindings)
  );

  /** Reads the configuration, and the library too when the person may choose. */
  async load({ library = false } = {}): Promise<void> {
    this.loadError = null;
    await Promise.all([
      this.#readConfiguration(),
      library && this.canEdit ? this.#readLibrary() : undefined
    ]);
  }

  setMode(row: OwnSkillRow, mode: PersonalSkillMode): void {
    if (mode === row.mode) return;
    void this.#save(row.id, withPersonalSkillMode(this.bindings, row, mode));
  }

  useLatestRevision(row: OwnSkillRow): void {
    if (!row.binding || !row.hasNewerRevision) return;
    void this.#save(row.id, withLatestPersonalSkillRevision(this.bindings, row.binding));
  }

  async #save(skillId: string, bindings: AssistantSkillBindingInput[]): Promise<void> {
    const change = ++this.#changes;
    this.#draft = bindings;
    this.saveError = null;
    let failure: unknown = null;
    try {
      await this.#sources.save(bindings);
    } catch (error) {
      failure = error;
    }
    // A later change was queued behind this one and settles after it.
    if (change !== this.#changes) return;
    await this.#readConfiguration();
    if (change !== this.#changes) return;
    this.#draft = null;
    if (failure !== null) {
      this.saveError = { skillId, message: personalSkillsSaveErrorMessage(failure) };
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
