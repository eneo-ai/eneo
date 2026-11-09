import { Token } from "@astryxdesign/core/Token";
import { useTranslations } from "use-intl";

/**
 * Speakers in a transcript: each label keeps one colour wherever it shows,
 * and its badge always carries the name in words, so the colour is never
 * the only way to tell speakers apart.
 */

type Translator = ReturnType<typeof useTranslations>;
type TokenColor = "blue" | "teal" | "purple" | "pink" | "green" | "cyan" | "yellow";

/** Orange and gray stay free for the transcript's own marks (unsure, overlap). */
const PALETTE: readonly TokenColor[] = [
  "blue",
  "teal",
  "purple",
  "pink",
  "green",
  "cyan",
  "yellow"
];

/** A speaker label's colour: `SPEAKER_NN` by its number, any other label by its text. */
export function speakerColor(label: string): TokenColor {
  const numbered = /^SPEAKER_(\d+)$/.exec(label);
  if (numbered) return PALETTE[Number(numbered[1]) % PALETTE.length]!;
  let hash = 0;
  for (const char of label) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length]!;
}

/**
 * The speaker's name; else, for a diarization label, "Talare 1" for
 * `SPEAKER_00` (any other label as it is); else "unknown speaker".
 */
export function speakerText(
  label: string | null,
  names: Record<string, string | null | undefined>,
  t: Translator
): string {
  if (!label) return t("flow_runs_transcript_unknown_speaker");
  const name = names[label]?.trim();
  if (name) return name;
  const numbered = /^SPEAKER_(\d+)$/.exec(label);
  return numbered
    ? t("flow_transcript_speaker_numbered", { number: Number(numbered[1]) + 1 })
    : label;
}

/**
 * Who said a line or a turn. The colon after it is for reading and copying
 * the text, not for the eye.
 */
export function SpeakerBadge({ label, name }: { label: string | null; name: string | null }) {
  const t = useTranslations();
  return (
    <>
      <Token
        size="sm"
        color={label ? speakerColor(label) : "default"}
        label={name ?? speakerText(label, {}, t)}
      />
      <span className="sr-only">:</span>
    </>
  );
}
