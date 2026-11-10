import type { Catalog } from "@astryxdesign/core/i18n";

/**
 * Swedish for the Astryx strings its sv-SE catalog (0.7.12) does not have yet,
 * in the components we render. Merged under Astryx's catalog, so a string
 * Astryx later translates wins. astryx-sv.test.ts lists the components.
 */
const SV: Record<string, string> = {
  "@astryx.chat.pastedText.label":
    "{lines, plural, =1 {{chars, plural, other {{chars} tecken}}} other {{lines} rader, {chars, plural, other {{chars} tecken}}}}",
  "@astryx.chatTriggerMenu.searching": "Söker…",
  "@astryx.commandPalette.input.label": "Sök kommandon",
  "@astryx.dateInput.calendarDescription": "Datum anges i {calendar}",
  "@astryx.dateInput.formatHint": "t.ex. {example}",
  "@astryx.dateInput.nonexistentDate": "Datumet finns inte i {calendar}",
  "@astryx.dateInput.outOfRangeDate":
    "{bounds, select, both {Ange ett datum från {min} till {max}} min {Ange ett datum från och med {min}} max {Ange ett datum till och med {max}} other {Datumet går inte att välja}}",
  "@astryx.dropdownMenu.backTo": "Tillbaka till {parent}",
  "@astryx.fileInput.fileSize.bytes": "{size, number, ::group-off} B",
  "@astryx.fileInput.fileSize.kilobytes": "{size, number, :: .0 group-off} kB",
  "@astryx.fileInput.fileSize.megabytes": "{size, number, :: .0 group-off} MB",
  "@astryx.inputClearButton.tooltip": "Rensa",
  "@astryx.kbd.key.alt": "Alt",
  "@astryx.kbd.key.altShort": "Alt",
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
  "@astryx.kbd.key.shiftShort": "Skift",
  "@astryx.kbd.key.tab": "Tabb",
  "@astryx.kbd.key.up": "Uppåtpil",
  "@astryx.kbd.key.windowsShort": "Win",
  "@astryx.kbd.shortcut": "{shortcut} + {key}",
  "@astryx.list.reorderCancelled":
    "Flytten avbröts, tillbaka på plats {position, number} av {total, number}",
  "@astryx.list.reorderDone": "Klart",
  "@astryx.list.reorderDropped": "Släppt, plats {position, number} av {total, number}",
  "@astryx.list.reorderHandle": "Flytta {label}",
  "@astryx.list.reorderHandleAt": "Flytta objekt {position, number}",
  "@astryx.list.reorderHandleVerb": "Flytta",
  "@astryx.list.reorderHint":
    "Dra för att flytta objektet, eller tryck på blanksteg eller Retur och sedan på piltangenterna för att flytta det ett steg i taget. Tryck på Escape när du är klar.",
  "@astryx.list.reorderItemAt": "Objekt {position, number}",
  "@astryx.list.reorderModeDone": "Klart, {label} på plats {position, number} av {total, number}",
  "@astryx.list.reorderMoveDown": "Flytta ner",
  "@astryx.list.reorderMoveUp": "Flytta upp",
  "@astryx.list.reorderPickedUp": "Lyft, plats {position, number} av {total, number}.",
  "@astryx.list.reorderPlace":
    "{label}, plats {position, number} av {total, number}, efter {previous}, före {next}",
  "@astryx.list.reorderPlaceEnd":
    "{label}, plats {position, number} av {total, number}, efter {previous}, sist",
  "@astryx.list.reorderPlaceTop":
    "{label}, plats {position, number} av {total, number}, först, före {next}",
  "@astryx.list.reorderRefused": "Kan inte flytta förbi {label}",
  "@astryx.multiSelector.createOption": "Skapa ”{query}”",
  "@astryx.multiSelector.optionCreated": "{label} skapades",
  "@astryx.multiSelector.selectedCount": "{count, plural, one {# vald} other {# valda}}",
  "@astryx.numberInput.invalidNumber": "Ogiltigt tal",
  "@astryx.switch.loading": "Läser in",
  "@astryx.table.columnResize.resizeColumn": "Ändra bredd på kolumnen {label}",
  "@astryx.table.columnResize.widthValue":
    "{width, number} {width, plural, one {pixel} other {pixlar}}",
  "@astryx.table.selection.bulkActionsLabel": "Åtgärder för markerade rader",
  "@astryx.table.selection.clearAll": "Avmarkera alla",
  "@astryx.table.selection.selectedCount": "{count, number} markerade",
  "@astryx.table.sort.priority": "Sorteringsordning {rank, number} av {total, number}",
  "@astryx.textArea.counter": "{count, number}/{limit, number}",
  "@astryx.tokenizer.add": "Lägg till",
  "@astryx.tokenizer.addValue": "Lägg till {value}",
  "@astryx.tokenizer.allRemoved": "Alla valda objekt togs bort",
  "@astryx.tokenizer.clearAllDescription": "Det här tar bort alla valda objekt från {label}.",
  "@astryx.tokenizer.clearAllTitle": "Rensa alla valda objekt?",
  "@astryx.tokenizer.clearSelection": "Rensa markering",
  "@astryx.tokenizer.create": "Skapa ”{value}”",
  "@astryx.tokenizer.discardChanges": "Släng ändringarna",
  "@astryx.tokenizer.discardChangesDescription": "Dina ändringar i {label} har inte sparats.",
  "@astryx.tokenizer.discardChangesTitle": "Släng ändringarna?",
  "@astryx.tokenizer.done": "Klart",
  "@astryx.tokenizer.keepEditing": "Fortsätt redigera",
  "@astryx.tokenizer.noResultsDescription": "Prova en annan sökning.",
  "@astryx.tokenizer.nothingToClear": "Inget valt",
  "@astryx.tokenizer.save": "Spara",
  "@astryx.tokenizer.search": "Sök i {label}",
  "@astryx.tokenizer.searchPlaceholder": "Sök…",
  "@astryx.tokenizer.selectedCount": "{count, number} valda",
  "@astryx.tokenizer.selectionLimit": "Välj högst {count, plural, one {# objekt} other {# objekt}}"
};

export const astryxSvSupplement: Catalog = Object.fromEntries(
  Object.entries(SV).map(([key, defaultMessage]) => [key, { defaultMessage }])
);
