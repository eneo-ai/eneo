import type { FlowLocale } from "$lib/features/flows/flowRunWizard";

export type FlowRunDialogLabels = ReturnType<typeof getFlowRunDialogLabels>;

export function getFlowRunDialogLabels(locale: FlowLocale) {
  if (locale === "sv") {
    return {
      progress: (current: number, total: number) => `${current} av ${total}`,
      previous: "Tillbaka",
      next: "Nästa",
      audio: "Ljud",
      file: "Fil",
      document: "Dokument",
      unnamedStep: (stepOrder: number) => `Steg ${stepOrder}`,
      templateReady: "Klar",
      templateNeedsAction: "Åtgärd krävs",
      templateReadOnly: "Skrivskyddad",
      templateUnavailable: "Otillgänglig",
      templateReadOnlyMessage: "Du kan köra flödet men inte byta mall.",
      templateNeedsActionMessage: "Mallen kräver åtgärd innan flödet kan köras.",
      templateStatusTitle: "Mallstatus",
      templateStatusDescription:
        "Kontrollera att publicerade DOCX-mallar fortfarande är tillgängliga innan du kör flödet.",
      templateFallbackName: (stepId: string) => `Mall för ${stepId}`,
      formIntroTitle: "Fyll i innan du kör flödet",
      formIntroDescription:
        "Fyll i de fält du skapade tidigare. Värdena blir sedan tillgängliga i flödet.",
      retryUpload: "Försök igen",
      disabledNextHint: "Fyll i obligatoriska fält först",
      runtimeGroupEyebrow: "Filer för denna körning",
      runtimeScopeHint: (stepOrder: number) => `Detta underlag används bara i steg ${stepOrder}.`,
      runtimeUploadHint: "Ladda upp fil eller dra den hit.",
      runtimeUploadingHint: "Uppladdning pågår. Vänta tills filen är klar innan du går vidare.",
      runtimeStepUploadTitle: "Uppladdning för detta steg",
      allowedTypesToggle: "Visa tillåtna filtyper",
      maxFiles: (count: number) => `Max ${count}`,
      maxFilesReached: "Max antal filer har redan laddats upp för detta steg.",
      requiredBadge: "Obligatoriskt",
      selectedFiles: (count: number) =>
        `${count} fil${count === 1 ? "" : "er"} vald${count === 1 ? "" : "a"}`,
      runBlockersTitle: "Det här behöver lösas innan du kan köra flödet",
      reviewReady: "Allt som krävs är klart. Du kan köra flödet nu.",
      reviewSummaryTitle: "Det här följer med i körningen",
      reviewFieldsTitle: "Fält som skickas med",
      reviewTextTitle: "Text som skickas in",
      reviewFilesTitle: "Uppladdade filer",
      runtimeReviewStep: (stepOrder: number, stepLabel: string) =>
        `Steg ${stepOrder}: ${stepLabel}`,
      closeConfirmTitle: "Du har osparade uppgifter",
      closeConfirmMessage: "Om du stänger dialogen försvinner uppladdade filer och ifyllda fält.",
      closeConfirmDiscard: "Stäng ändå",
      closeConfirmKeep: "Fortsätt redigera",
      technicalMimeToggle: "Visa tekniska MIME-typer"
    };
  }

  return {
    progress: (current: number, total: number) => `${current} of ${total}`,
    previous: "Back",
    next: "Next",
    audio: "Audio",
    file: "File",
    document: "Document",
    unnamedStep: (stepOrder: number) => `Step ${stepOrder}`,
    templateReady: "Ready",
    templateNeedsAction: "Needs action",
    templateReadOnly: "Read-only",
    templateUnavailable: "Unavailable",
    templateReadOnlyMessage: "You can run the flow but you cannot change the template.",
    templateNeedsActionMessage: "The template needs attention before the flow can run.",
    templateStatusTitle: "Template status",
    templateStatusDescription:
      "Check that published DOCX templates are still available before you run the flow.",
    templateFallbackName: (stepId: string) => `Template for ${stepId}`,
    formIntroTitle: "Fill in before running the flow",
    formIntroDescription:
      "Fill in the fields you created earlier. The values will then be available in the flow.",
    retryUpload: "Try again",
    disabledNextHint: "Fill in required fields first",
    runtimeGroupEyebrow: "Files for this run",
    runtimeScopeHint: (stepOrder: number) => `This material is only used in step ${stepOrder}.`,
    runtimeUploadHint: "Upload a file or drag it here.",
    runtimeUploadingHint: "Upload in progress. Wait until the file is finished before continuing.",
    runtimeStepUploadTitle: "Upload for this step",
    allowedTypesToggle: "Show allowed file types",
    maxFiles: (count: number) => `Max ${count}`,
    maxFilesReached: "The maximum number of files has already been uploaded for this step.",
    requiredBadge: "Required",
    selectedFiles: (count: number) => `${count} file${count === 1 ? "" : "s"} selected`,
    runBlockersTitle: "This still needs to be resolved before you can run the flow",
    reviewReady: "Everything required is ready. You can run the flow now.",
    reviewSummaryTitle: "Included in this run",
    reviewFieldsTitle: "Fields that will be sent",
    reviewTextTitle: "Text that will be sent",
    reviewFilesTitle: "Uploaded files",
    runtimeReviewStep: (stepOrder: number, stepLabel: string) => `Step ${stepOrder}: ${stepLabel}`,
    closeConfirmTitle: "You have unsaved changes",
    closeConfirmMessage: "Closing this dialog will discard uploaded files and filled-in fields.",
    closeConfirmDiscard: "Discard and close",
    closeConfirmKeep: "Keep editing",
    technicalMimeToggle: "Show technical MIME types"
  };
}
