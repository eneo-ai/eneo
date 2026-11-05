import type { Catalog } from "@astryxdesign/core/i18n";

/**
 * Swedish for the Astryx strings its sv-SE catalog (0.7.5) does not have yet,
 * in the components we render. Merged under Astryx's catalog, so a string
 * Astryx later translates wins. astryx-sv.test.ts lists the components.
 */
const SV: Record<string, string> = {
  "@astryx.chat.pastedText.label":
    "{lines, plural, =1 {{chars, plural, other {{chars} tecken}}} other {{lines} rader, {chars, plural, other {{chars} tecken}}}}",
  "@astryx.chatTriggerMenu.searching": "Söker…",
  "@astryx.commandPalette.input.label": "Sök kommandon",
  "@astryx.dropdownMenu.backTo": "Tillbaka till {parent}",
  "@astryx.fileInput.fileSize.bytes": "{size, number, ::group-off} B",
  "@astryx.fileInput.fileSize.kilobytes": "{size, number, :: .0 group-off} kB",
  "@astryx.fileInput.fileSize.megabytes": "{size, number, :: .0 group-off} MB",
  "@astryx.inputClearButton.tooltip": "Rensa",
  "@astryx.kbd.key.alt": "Alt",
  "@astryx.kbd.key.backspace": "Backsteg",
  "@astryx.kbd.key.command": "Kommando",
  "@astryx.kbd.key.control": "Control",
  "@astryx.kbd.key.controlShort": "Ctrl",
  "@astryx.kbd.key.down": "Nedåtpil",
  "@astryx.kbd.key.enter": "Retur",
  "@astryx.kbd.key.escape": "Escape",
  "@astryx.kbd.key.escapeShort": "Esc",
  "@astryx.kbd.key.left": "Vänsterpil",
  "@astryx.kbd.key.plus": "Plus",
  "@astryx.kbd.key.right": "Högerpil",
  "@astryx.kbd.key.shift": "Skift",
  "@astryx.kbd.key.tab": "Tabb",
  "@astryx.kbd.key.up": "Uppåtpil",
  "@astryx.kbd.shortcut": "{shortcut} + {key}",
  "@astryx.multiSelector.createOption": "Skapa ”{query}”",
  "@astryx.multiSelector.optionCreated": "{label} skapades",
  "@astryx.numberInput.invalidNumber": "Ogiltigt tal",
  "@astryx.switch.loading": "Läser in",
  "@astryx.table.selection.bulkActionsLabel": "Åtgärder för markerade rader",
  "@astryx.table.selection.clearAll": "Avmarkera alla",
  "@astryx.table.selection.selectedCount": "{count, number} markerade",
  "@astryx.tokenizer.add": "Lägg till",
  "@astryx.tokenizer.addValue": "Lägg till {value}",
  "@astryx.tokenizer.allRemoved": "Alla valda objekt togs bort",
  "@astryx.tokenizer.clearAllDescription": "Det här tar bort alla valda objekt från {label}.",
  "@astryx.tokenizer.clearAllTitle": "Rensa alla valda objekt?",
  "@astryx.tokenizer.clearSelection": "Rensa markering",
  "@astryx.tokenizer.create": "Skapa ”{value}”",
  "@astryx.tokenizer.done": "Klart",
  "@astryx.tokenizer.noResultsDescription": "Prova en annan sökning.",
  "@astryx.tokenizer.nothingToClear": "Inget valt",
  "@astryx.tokenizer.search": "Sök i {label}",
  "@astryx.tokenizer.searchPlaceholder": "Sök…",
  "@astryx.tokenizer.selectedCount": "{count, number} valda"
};

export const astryxSvSupplement: Catalog = Object.fromEntries(
  Object.entries(SV).map(([key, defaultMessage]) => [key, { defaultMessage }])
);
