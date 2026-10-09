/**
 * The text of one polite live region. Screen readers stay silent when a
 * region receives the text it already holds (a second identical answer or
 * "copied"), so each announcement first empties the region and fills it once
 * that has been seen. The text is cleared again afterwards so a screen reader
 * user reading through the page does not meet it a second time.
 */
export class Announcer {
  text = $state("");

  #timer: ReturnType<typeof setTimeout> | null = null;

  announce(message: string): void {
    this.clear();
    this.#timer = setTimeout(() => {
      this.text = message;
      this.#timer = setTimeout(() => this.clear(), 5000);
    }, 150);
  }

  clear(): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    this.text = "";
  }
}
