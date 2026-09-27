<!--
    Drop area wired to the surrounding AttachmentManager: picked files are
    queued for upload straight away and validation problems are shown inline.
-->
<script lang="ts">
  import {
    getAttachmentManager,
    unsupportedTypeError,
    type AttachmentValidationError
  } from "../AttachmentManager";
  import FileDropzone, { type FileSelection } from "./FileDropzone.svelte";
  import FileSizeValidationPanel from "./FileSizeValidationPanel.svelte";

  type Props = {
    multiple?: boolean;
    description?: string;
  };

  let { multiple = false, description }: Props = $props();

  const {
    state: { attachmentRules },
    queueValidUploadsDetailed
  } = getAttachmentManager();

  let validationErrors = $state<AttachmentValidationError[]>([]);

  function handleSelection({ accepted, rejected }: FileSelection) {
    const errors = accepted.length > 0 ? (queueValidUploadsDetailed(accepted) ?? []) : [];
    validationErrors = [...rejected.map(unsupportedTypeError), ...errors];
  }
</script>

<FileDropzone
  formats={$attachmentRules.acceptedFormats ?? []}
  keepSelection={false}
  {multiple}
  {description}
  onselect={handleSelection}
/>
<FileSizeValidationPanel errors={validationErrors} />
