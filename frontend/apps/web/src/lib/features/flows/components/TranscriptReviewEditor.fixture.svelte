<script lang="ts">
  import TranscriptReviewEditor from "./TranscriptReviewEditor.svelte";
  import type { TranscriptSegment, TranscriptFileReview } from "../transcriptSegments";
  import type { ReviewDraft } from "../transcriptReviewEditor";
  let {
    speakerReviews = [],
    segments,
    onSave = () => {},
    onSeek = () => {},
    audioAvailable = true,
    editable = true,
    currentTime = 0,
    playing = false
  }: {
    segments: TranscriptSegment[];
    speakerReviews?: TranscriptFileReview[];
    onSave?: (draft: ReviewDraft) => void;
    onSeek?: (file: number, time: number, play: boolean, end?: number) => void;
    audioAvailable?: boolean;
    editable?: boolean;
    currentTime?: number;
    playing?: boolean;
  } = $props();
  let draft = $state<ReviewDraft>({ occurrences: [], speakerEdits: [] });
</script>

<TranscriptReviewEditor
  {segments}
  {speakerReviews}
  {draft}
  {audioAvailable}
  {editable}
  {currentTime}
  {playing}
  currentFile={0}
  displayName={(s) => (s === "SPEAKER_00" ? "Anna" : "Bo")}
  speakerOptions={["SPEAKER_00", "SPEAKER_01"]}
  {onSeek}
  onInteract={() => {}}
  onChange={async (next) => {
    draft = next;
    onSave(next);
    return true;
  }}
/>
