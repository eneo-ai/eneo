import { dynamicColour } from "$lib/core/colours";
import { createContext } from "$lib/core/context";
import type { ConversationTools } from "@intric/intric-js";
import type { ActionReturn } from "svelte/action";
import { derived, get, readonly, writable } from "svelte/store";

const [getMentionInput, setMentionInput] =
  createContext<ReturnType<typeof createMentionInput>>("Mention input");

type AssistantSuggestion = {
  id: string;
  handle: string;
  head: string;
  match: string;
  tail: string;
};

type MentionInputParams = {
  triggerCharacter: string;
  tools: () => ConversationTools;
  onEnterPressed?: () => void;
};

function initMentionInput(data: MentionInputParams) {
  const input = createMentionInput(data);
  setMentionInput(input);
  return input;
}

export { initMentionInput, getMentionInput };

export function createMentionInput(params: MentionInputParams) {
  const { triggerCharacter, tools } = params;
  const showSuggestions = writable(false);
  const suggestions = writable<AssistantSuggestion[]>([]);
  const triggerPosition = writable<{ bottom: number; left: number } | undefined>(undefined);
  const selectedIndex = writable(0);
  const mentions = writable<AssistantSuggestion[]>([]);
  const question = writable("");
  let inputNode: HTMLElement | undefined;

  function input(node: HTMLElement): ActionReturn {
    inputNode = node;
    window.addEventListener("click", handleWindowClick);
    node.addEventListener("input", handleInputSuggestions);
    node.addEventListener("click", handleInputClick);
    node.addEventListener("keydown", handleInputKeydown);
    node.addEventListener("paste", handlePaste);

    const observer = new MutationObserver(handleInputMutation);
    observer.observe(node, { childList: true, characterData: true, subtree: true });

    // Seed `question` from whatever is already in the editor when this action
    // attaches. Hydration can land after text was typed into the SSR-rendered
    // contenteditable; the observer only fires on *future* mutations, so that
    // pre-attach text would otherwise never reach `question` and the send button
    // would stay disabled until the next keystroke.
    if (node.textContent) {
      handleInputMutation();
    }

    return {
      destroy() {
        window.removeEventListener("click", handleWindowClick);
        node.removeEventListener("keydown", handleInputKeydown);
        node.removeEventListener("click", handleInputClick);
        node.removeEventListener("input", handleInputSuggestions);
        node.removeEventListener("paste", handlePaste);
        observer.disconnect();
      }
    };
  }

  function resetMentionInput() {
    if (!inputNode) {
      throw new Error("Can't reset MentionInput: inputNode node defined");
    }
    mentions.set([]);
    inputNode.innerHTML = "";
    question.set("");
    selectedIndex.set(0);
  }

  function setQuestionText(text: string) {
    question.set(text);
    if (inputNode) {
      inputNode.textContent = text;
    }
  }

  function handleInputSuggestions(event: Event) {
    if (!(event instanceof InputEvent)) return;
    let shouldShowSuggestions = get(showSuggestions);
    let matchingSuggestions = get(suggestions);

    if (event.data === triggerCharacter) {
      triggerPosition.set(getCaretPosition());
      // TODO ??? At this point in time we only support one mention per message
      shouldShowSuggestions = get(mentions).length === 0;
    }

    if (shouldShowSuggestions) {
      matchingSuggestions = getMatchingSuggestions();
    }

    if (matchingSuggestions.length === 0) {
      // shouldShowSuggestions = false;
    } else {
      selectedIndex.set(0); // Reset selected index when suggestions change
    }

    showSuggestions.set(shouldShowSuggestions);
    suggestions.set(matchingSuggestions);
  }

  function getCaretPosition() {
    const selection = window.getSelection();
    // focusNode is text -> parentNode is contenteditable -> parentNode is whole input section
    const inputRect = selection?.focusNode?.parentElement?.parentElement?.getClientRects()[0];
    const rangeRect = selection?.getRangeAt(0).getClientRects()[0];

    if (!inputRect || !rangeRect) return undefined;

    // We position the bottom at the top of the input
    // And the left we can subtract to get the relative offset into the editable
    return { bottom: rangeRect.height, left: rangeRect.left - inputRect.left };
  }

  function getMatchingSuggestions() {
    // Check for valid selection
    const selection = window.getSelection();
    if (!selection?.focusNode?.nodeValue) return [];

    // Check if trigger character is in selection
    const triggerOffset = selection.focusNode.nodeValue.lastIndexOf(
      triggerCharacter,
      selection.focusOffset - 1
    );
    if (triggerOffset < 0) return [];

    const partial = selection.focusNode.nodeValue
      .slice(triggerOffset + 1, selection.focusOffset)
      .replace("\u00A0", " ") // Trailing spaces are non-breaking spaces, otherwise they would get trimmed
      .toLowerCase();

    return tools()
      .assistants.map((option) => {
        const tagLower = option["handle"].toLowerCase();
        const matchStart = tagLower.indexOf(partial);

        return { ...option, tagLower, matchStart };
      })
      .filter((option) => option.matchStart !== -1)
      .sort((a, b) => a.matchStart - b.matchStart)
      .map((suggestion) => {
        const name = suggestion["handle"];
        const { head, match, tail } = extractMatchParts(
          name,
          suggestion.matchStart,
          partial.length
        );

        return { ...suggestion, head, match, tail };
      });
  }

  function handleInputClick() {
    disableSuggestions();
  }

  function moveCursor(position: "before" | "after" | "startOf" | "endOf", node: Node) {
    const aux_range = new Range();
    if (position === "before") {
      aux_range.setStartBefore(node);
    } else if (position === "after") {
      aux_range.setStartAfter(node);
    } else if (position === "startOf") {
      aux_range.setStart(node, 0);
    } else if (position === "endOf") {
      aux_range.selectNodeContents(node);
      aux_range.collapse();
    }
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(aux_range);
  }

  function handleInputMutation() {
    const inner = inputNode?.childNodes;
    if (!inner) return;

    let content = "";

    for (const node of inner) {
      if (nodeIsElement(node)) {
        // Keep new lines
        if (node.tagName === "BR") {
          content += "\n";
          continue;
        }

        // When pasting text with execCommand the browser wraps every line in a div and does not add <br> elements.
        // We prepend a newline to keep these line breaks in our question string.
        if (node.tagName === "DIV") {
          content += "\n" + node.textContent;
          continue;
        }

        // Add mention syntax
        if (nodeIsMention(node)) {
          content += `[[${node.innerText}]]`;
          continue;
        }
      }

      content += node.textContent;
    }

    question.set(content.trim());
  }

  function handleInputKeydown(event: KeyboardEvent) {
    const selection = window.getSelection();
    if (!selection || !selection.focusNode) return;

    const { parentNode, previousSibling, nextSibling } = selection.focusNode;

    if (event.key === "ArrowUp") {
      if (get(showSuggestions)) {
        event.preventDefault();
        selectedIndex.update((i) => (i > 0 ? i - 1 : get(suggestions).length - 1));
      } else {
        disableSuggestions();
      }
    }

    if (event.key === "ArrowDown") {
      if (get(showSuggestions)) {
        event.preventDefault();
        selectedIndex.update((i) => (i < get(suggestions).length - 1 ? i + 1 : 0));
      } else {
        disableSuggestions();
      }
    }

    if (event.key === "Enter") {
      if (get(showSuggestions)) {
        event.preventDefault();
        const selected = get(suggestions)[get(selectedIndex)];
        if (selected) {
          insertMentionNode(selected);
        }
      } else if (!event.shiftKey) {
        event.preventDefault();
        params.onEnterPressed?.();
      }
    }

    // Handle Tab key separately
    if (event.key === "Tab") {
      if (get(showSuggestions)) {
        event.preventDefault();
        const selected = get(suggestions)[get(selectedIndex)];
        if (selected) {
          insertMentionNode(selected);
        }
      } else {
        // Insert a tab character when Tab is pressed
        event.preventDefault();
        document.execCommand("insertText", false, "\t");
      }
    }

    // Should also jump over a mention
    if (event.key === "ArrowLeft") {
      disableSuggestions();
      if (nodeIsMention(parentNode)) {
        // jump to before mention
        moveCursor("before", parentNode);
      } else if (nodeIsMention(previousSibling) && selection.focusOffset < 2) {
        // jump to before mention
        moveCursor("before", previousSibling);
      }
    }

    if (event.key === "ArrowRight") {
      disableSuggestions();
      if (nodeIsMention(parentNode)) {
        // Jump to after mention
        moveCursor("after", parentNode);
      } else if (
        nodeIsMention(nextSibling) &&
        // @ts-expect-error if node is a mention it will also have length
        selection.focusOffset > selection.focusNode.length - 2
      ) {
        // jump to after mention
        moveCursor("after", nextSibling);
      }
    }

    if (["Home", "End"].includes(event.key)) {
      disableSuggestions();
    }

    if (event.key === "Delete") {
      if (
        selection.isCollapsed &&
        nodeIsMention(nextSibling) &&
        // @ts-expect-error if node is a mention it will also have length
        selection.focusOffset === selection.focusNode.length
      ) {
        removeMention(nextSibling);
      } else {
        handleDeletion(selection, event);
      }
    }

    if (event.key === "Backspace") {
      if (selection.isCollapsed && nodeIsMention(previousSibling) && selection.focusOffset < 2) {
        removeMention(previousSibling);
      } else {
        handleDeletion(selection, event);
      }
    }

    if (event.key === "Escape") {
      disableSuggestions();
    }

    if (event.key === " ") {
      if (get(suggestions).length === 0) {
        disableSuggestions();
      }
    }

    if (nodeIsMention(parentNode)) {
      // If trying to edit inside mention, jump to end of mention
      if (event.code.startsWith("Key")) {
        const spaceNode = document.createTextNode("\u00A0");
        parentNode.after(spaceNode);
        moveCursor("after", spaceNode);
      }
    }
  }

  function disableSuggestions() {
    showSuggestions.set(false);
    suggestions.set([]);
  }

  function insertMentionNode(item: AssistantSuggestion) {
    mentions.update((m) => [...m, item]);

    // Check for valid selection
    const selection = window.getSelection();
    if (!selection?.focusNode?.nodeValue) return;

    // Check if trigger character is in selection
    const triggerOffset = selection.focusNode.nodeValue.lastIndexOf(
      triggerCharacter,
      selection.focusOffset - 1
    );
    if (triggerOffset < 0) return;

    // Delete partially written assistant name
    const range = new Range();
    range.setStart(selection.focusNode, triggerOffset);
    range.setEnd(selection.focusNode, selection.focusOffset);
    range.deleteContents();

    // Create and insert a "proper" mention
    const mention = document.createElement("span");
    mention.textContent = triggerCharacter + item["handle"];
    mention.dataset.value = JSON.stringify(item);
    mention.classList.add("mention");
    mention.dataset.dynamicColour = dynamicColour({ basedOn: item.id })["data-dynamic-colour"];
    range.insertNode(mention);

    // Insert a space after the mention and move cursor into it
    const spaceNode = document.createTextNode("\u00A0");
    mention.after(spaceNode);

    const aux_range = new Range();
    aux_range.setStartAfter(spaceNode);
    selection?.removeAllRanges();
    selection?.addRange(aux_range);

    // We can close the popup once the insertion is done
    disableSuggestions();
  }

  function handleDeletion(selection: Selection, event: KeyboardEvent) {
    const node = selection.focusNode;
    if (!node) return;

    // If we're inside a mention delete the whole thing
    if (nodeIsMention(node.parentNode)) {
      removeMention(node.parentNode);
      return;
    }

    // If the user hasn't made a selection we can just check the deleted char
    if (selection.isCollapsed) {
      const deletedChar =
        event.key === "Backspace"
          ? selection.focusNode.textContent?.[selection.focusOffset - 1]
          : selection.focusNode.textContent?.[selection.focusOffset];
      if (deletedChar === "@") disableSuggestions();
      return;
    }

    // If multiple nodes are selected we need to check if any of them was a mention
    const fragment = selection.getRangeAt(0).cloneContents();
    for (const child of fragment.childNodes) {
      if (nodeIsMention(child)) {
        removeMention(child);
      }
      if (child.textContent?.includes("@")) {
        disableSuggestions();
      }
    }

    setTimeout(() => {
      if (inputNode?.textContent === "") {
        moveCursor("startOf", inputNode);
      }
    }, 1);
  }

  function removeMention(node: HTMLSpanElement) {
    if (node.dataset.value) {
      try {
        const item = JSON.parse(node.dataset.value);
        mentions.update(($mentions) => {
          const idx = $mentions.findIndex((mention) => mention.id === item.id);
          if (idx > -1) {
            $mentions.splice(idx, 1);
          }
          return $mentions;
        });
      } catch {
        console.error("Couldn't remove mention value from mentions");
      }
    }
    node.parentNode?.removeChild(node);
  }

  function handlePaste(event: ClipboardEvent) {
    // This function should allow to paste text content into the mention input.
    // - We want to strip all formatting (contenteditable would keep colours, sizes, etc.)
    // - We only want the text
    // - There is a separate event handler registered for uploading images, directly in the component

    // No default event handling
    event.preventDefault();

    const text = event.clipboardData?.getData("text/plain");
    if (!text) return;

    // Use execCommand to insert text, which preserves undo history
    // This is deprecated, but after some research there is no real alternative except managing our own undo stack
    document.execCommand("insertText", false, text);

    // Make sure input stays in view
    inputNode?.scrollIntoView(false);
  }

  function handleWindowClick(event: Event) {
    if (get(showSuggestions)) {
      event.preventDefault();
      disableSuggestions();
    }
  }

  function suggestionList(node: HTMLElement): ActionReturn {
    const unsubToggle = suggestions.subscribe((suggestions: AssistantSuggestion[]) => {
      node.style.display = suggestions.length > 0 && get(showSuggestions) ? "flex" : "none";
      setTimeout(() => {
        const selectedElement = node.querySelector('[data-selected="true"]');
        if (selectedElement) {
          selectedElement.scrollIntoView({ block: "nearest", inline: "nearest" });
        }
      }, 1);
    });

    const unsubTrigger = triggerPosition.subscribe(({ bottom, left } = { bottom: 0, left: 0 }) => {
      node.style.left = left + "px";
      node.style.bottom = bottom + "px";
    });

    const unsubScroller = selectedIndex.subscribe((idx) => {
      if (idx > -1 && get(showSuggestions)) {
        setTimeout(() => {
          const selectedElement = node.querySelector('[data-selected="true"]');
          if (selectedElement) {
            selectedElement.scrollIntoView({ block: "nearest", inline: "nearest" });
          }
        }, 1);
      }
    });

    return {
      destroy() {
        unsubToggle();
        unsubTrigger();
        unsubScroller();
      }
    };
  }

  function showMentionPicker(event: Event) {
    if (!inputNode) return;
    let selection = window.getSelection();
    // If no selection or wrong element in focus try to focus the input
    if (!selectionFound(selection) || selection?.focusNode !== inputNode) {
      inputNode.focus();
      selection = window.getSelection();
    }

    if (!selectionFound(selection)) return;
    const range = selection.getRangeAt(0);

    // Allowing event default would take away focus from inputNode
    event.preventDefault();
    // Stop propagation so we dont trigger the window handler (which closes the popup)
    event.stopPropagation();

    inputNode.focus();

    const isAtStart = range.startOffset === 0;
    const prevChar = selection.focusNode?.nodeValue?.[selection.focusOffset - 1];
    const isAfterSpace = isAtStart || prevChar === "\u00A0" || prevChar === " ";

    const triggerSequence = isAfterSpace ? triggerCharacter : " " + triggerCharacter;
    const textNode = document.createTextNode(triggerSequence);

    if (inputNode.textContent === "") {
      inputNode.replaceChildren(textNode);
    } else {
      range.deleteContents();
      range.insertNode(textNode);
    }

    range.selectNodeContents(textNode);
    range.collapse();

    selection.removeAllRanges();
    selection.addRange(range);

    inputNode.dispatchEvent(
      new InputEvent("input", {
        data: triggerCharacter
      })
    );
  }

  return {
    elements: { input, suggestionList },
    states: {
      showSuggestions,
      suggestions,
      triggerPosition,
      selectedIndex,
      mentions: derived(mentions, ($mentions) =>
        // Filter out duplicates
        $mentions.filter((value, idx, self) => idx === self.findIndex((other) => other === value))
      ),
      question: readonly(question)
    },
    insertMentionNode,
    showMentionPicker,
    resetMentionInput,
    setQuestionText,
    focusMentionInput: () => {
      inputNode?.focus();
    }
  };
}

function selectionFound(selection: Selection | null): selection is Selection {
  return selection !== null && selection.rangeCount > 0;
}

function nodeIsMention(node: Node | null | undefined): node is HTMLSpanElement {
  if (!node) return false;
  return node.nodeType === Node.ELEMENT_NODE && (node as Element).classList.contains("mention");
}

function nodeIsElement(node: Node | null | undefined): node is HTMLElement {
  if (!node) return false;
  return node.nodeType === Node.ELEMENT_NODE;
}

/**
 * In order to be able to show the matching part of an assistant name bold,
 * we need to split it into three parts
 */
function extractMatchParts(name: string, matchStart: number, matchLength: number) {
  return {
    head: name.slice(0, matchStart),
    match: name.slice(matchStart, matchStart + matchLength),
    tail: name.slice(matchStart + matchLength)
  };
}
