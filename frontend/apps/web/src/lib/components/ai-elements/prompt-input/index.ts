import Root from "./prompt-input.svelte";
import Body from "./prompt-input-body.svelte";
import Footer from "./prompt-input-footer.svelte";
import Tools from "./prompt-input-tools.svelte";
import Button from "./prompt-input-button.svelte";
import Submit from "./prompt-input-submit.svelte";

export type { PromptInputStatus } from "./context";

export {
  Root,
  Body,
  Footer,
  Tools,
  Button,
  Submit,
  //
  Root as PromptInput,
  Body as PromptInputBody,
  Footer as PromptInputFooter,
  Tools as PromptInputTools,
  Button as PromptInputButton,
  Submit as PromptInputSubmit
};
