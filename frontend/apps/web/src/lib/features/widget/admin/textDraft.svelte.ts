import { untrack } from "svelte";

/** The whitespace collapse the API applies to names and visitor-facing texts. */
export function collapseWhitespace(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * The text an autosaved field shows while the server echoes its value back.
 *
 * The API stores texts normalised, so the echo of "Välkommen till " is
 * "Välkommen till". Written into the field being typed in, that eats the
 * space and glues the next word on. The draft keeps what the editor typed
 * while the saved value is only its normalised form, follows the saved value
 * whenever it really changes (another editor, a template, a reload), and
 * settles on the saved form once the field is left.
 *
 * Create it during component initialisation: it registers an effect.
 */
export class TextDraft {
  text = $state("");
  #saved: () => string;
  #normalize: (text: string) => string | null;
  #seen: string;
  #focused = false;

  constructor(
    saved: () => string,
    normalize: (text: string) => string | null = collapseWhitespace
  ) {
    this.#saved = saved;
    this.#normalize = normalize;
    this.#seen = untrack(saved);
    this.text = this.#seen;
    $effect(() => {
      const value = saved();
      untrack(() => this.#follow(value));
    });
  }

  #follow(value: string) {
    // A fresh response with the same content is not news.
    if (value === this.#seen) return;
    this.#seen = value;
    if (this.#focused && value === this.#normalize(this.text)) return;
    this.text = value;
  }

  focus = () => {
    this.#focused = true;
  };

  blur = () => {
    this.#focused = false;
    const saved = this.#saved();
    if (saved !== this.text && saved === this.#normalize(this.text)) this.text = saved;
  };
}
