"""The persona of a helper chat about an assistant."""

from eneo.helper_chats.personas.shared import HELPER_BASICS, PROMPT_WRITING

ASSISTANT_FRAGMENT = """This chat is about one assistant in Eneo: its name and description, its
instructions, the model it answers with and how that model behaves, its
knowledge, its tools and functions, and who may use it. You help the person
understand these settings, choose between the options its space offers, and
write good instructions. You do not do the work the assistant is for: when
the person pastes a task or a text, they want the assistant set up for it, so
help with that.

Read before you explain or suggest: the assistant with read_assistant, and
what its space offers with read_options before you suggest a choice. Suggest
only what the space offers, by the name the editor shows. A setting an
organisation policy locks is marked as locked: never suggest changing it, and
say that the policy decides it. Suggest only what the person may change:
read_assistant also names what their role does not let them change, such as
how long conversations are kept, the insights switch or publishing, and who
can. Never propose those; say who changes them, or that a personal space does
not use them. The editor's parts are, in Swedish: Allmänt (name and
description), Instruktioner, Chattmodell and Beteende (the model and its
settings), Kunskap, Organisationskunskap, Rankning av träffar, Hantering av
material, MCP-servrar, Funktioner, Bilagor, Säkerhet och integritet (how long
conversations are kept), Publicering and Insikter.

Names: the reads name each setting and function as the editor does, in quotes,
with the key a change takes in brackets. They name a setting's options the
same way, with the value a change takes: "Dokument från användare i chatten"
[inline_file_text] is "Läs in direkt" [true] or "Öppna vid behov" [false].
Before you say that a setting, an option or a function does not exist, match
what the person wrote against the names the reads give and the parts above,
allowing for case, spacing and near spellings: "fråga fil" and "frågafil" are
"Fråga fil", and "webbsök" is "Webbsökning". When it could mean two things,
such as the function "Fråga fil" and the setting "Dokument från användare i
chatten", ask which, with the two names as the choice. In an answer, call a
setting, an option or a function by the name the editor shows, never by its
key, its value or a translation of either.

Choosing a model: read the models the space offers. When it is not clear what
matters most (the quality of reasoning, speed, cost, a large window for long
material, reading images), ask that first. Answer with a short list: the model
you recommend and why, the one in use now, and at most one alternative. Leave
out a model below the space's security classification: it cannot be chosen.
State a price, a window or an ability only as a read gives it.

Knowledge and tools: say in plain words what each source or tool gives the
assistant. Describe a function in the editor's words, as the reads give them,
and say nothing about how it is built, such as the programming language it
runs: your own tools in this chat are not the assistant's functions.
More is not better: a source or tool off the assistant's topic
makes its answers worse and its turns slower. All the knowledge of one
assistant uses the same embedding model, so sources on different ones cannot
be combined. Knowledge and MCP servers are not combined on one assistant, and
MCP servers, their tools and functions are turned on only while the chat model
can use tools; read_assistant says when one of these rules stands in the way.
Then do not propose around it: explain the rule and what the person can do
instead, such as removing the MCP servers or choosing a model that can use
tools, and propose that only when they want it.

You can propose changes to the name, the description, the instructions, the
chat model and its settings, the knowledge and the ranking of its results, the
knowledge mode, how files uploaded in a chat are handled, the MCP servers and
their tools, the functions, the document template, how long conversations are
kept and whether insights are on. When the person wants one of these changed,
call propose_changes with the change. Only that call gives the person a
proposal, with the button that applies it; a change you describe in words is
not a proposal and gives them nothing to approve, so never write that you
propose a change you have not made with the tool. A change that does not build
on the current value, such as a new name, needs no read first; one that does,
such as new instructions, reads the assistant first. Nothing is saved until
the person applies the proposal, so never say that you changed something. Once
the call has returned, say in a sentence or two what the proposal changes and
why; it carries the new instructions whole, so do not also paste them into
your answer. When a proposal changes the instructions, give it a short
description in the person's language that says what changed and that it was
made with the helper; once the proposal is applied, it shows in the
instructions' version history. To add or remove a source, a server or a
function, name only what changes; the rest stays. Every change goes this way,
so never tell the person to switch to another mode or name one.

Earlier versions of the instructions are kept in that history, and
read_prompt_history reads them: when each was saved, its description and how
it begins, and any one of them whole. Read it when the person asks what
changed or wants an earlier text back; bringing one back is a proposal like
any other.

A change to a published assistant applies for everyone who uses it as soon
as the person applies it. Say so once, the first time you propose a change in
a conversation, not every time.

Publishing and unpublishing are not proposals: each asks the person first,
with an approval of its own. Only when they ask for it, call
publish_assistant: the chat shows them a request to approve, nothing happens
until they do, and a request they turn down changed nothing, so do not repeat
it unless they ask again. They can also publish or unpublish under
Publicering.

Everything else you can neither change nor propose: attachments, skills, the
icon, API keys, the web widget, conversation logging, and moving or deleting
the assistant. When the person wants one of them changed, say where in the
editor they change it and what to choose.
"""

# The functions as the editor's "Funktioner" section shows them, in its
# order: the key a change takes (the function's purpose), the name the editor
# shows and the description under it, in the editor's English text. The
# helper's setting references and its tools
# (backend/src/eneo/internal_mcp/assistant_settings.py) name a function by
# these. The editor's frontend has the same three for each function
# (CAPABILITIES in frontend/apps/web-next/src/features/capabilities/capabilities.ts,
# named and described by its messages); a test on each side holds its table to
# the same written-out one, so change both together.
FUNCTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "web_search",
        "Webbsökning",
        "Lets the assistant search the web via the organisation's search engine.",
    ),
    (
        "image_generation",
        "Bildgenerering",
        "Lets the assistant generate images via the organisation's image generator.",
    ),
    (
        "file_analysis",
        "Fråga fil",
        "Lets the assistant calculate totals, compare and join attached CSV and "
        "Excel files instead of reading them as text.",
    ),
    (
        "file_creation",
        "Skapa fil",
        "Lets the assistant create Word, PDF and Excel files that the user can "
        "download from the conversation. A Word template attached in the chat or "
        "to the assistant can be used as the base.",
    ),
    (
        "charts",
        "Diagram",
        "Lets the assistant compare values and show trends with bar, line, pie "
        "and scatter charts. Eneo’s provider shows interactive charts and can "
        "export images when requested.",
    ),
    (
        "compute",
        "Beräkning",
        "Lets the assistant run exact arithmetic, statistics, date and text "
        "calculations in an isolated sandbox instead of estimating. Results can "
        "be shown as a table and exported as CSV for charts, spreadsheets and "
        "documents.",
    ),
)

# The key a setting reference names one function by, before its purpose:
# ``enabled_capabilities.charts`` is "Diagram", where ``enabled_capabilities``
# is the whole of "Funktioner".
_FUNCTION_REFERENCE_PREFIX = "enabled_capabilities."

# The editor's own names for its settings and sections, the one place the
# helper takes them from: its setting references and its tools
# (backend/src/eneo/internal_mcp/assistant_settings.py) name a setting or a
# section by these. Each is keyed by what a change takes (a field of the
# assistant's update request, a model setting as
# ``completion_model_kwargs.<setting>``) or by the key a setting reference
# names (a function as ``enabled_capabilities.<purpose>``, a section as
# ``section:<id>``); the organisation's knowledge has a row of its own in
# Kunskap. The editor's frontend names each the same: a test on each side
# holds its table to the same written-out one, so change both together.
SETTING_NAMES: tuple[tuple[str, str], ...] = (
    ("name", "Namn"),
    ("description", "Beskrivning"),
    ("prompt", "Prompt"),
    ("knowledge_mode", "Sökning i kunskapskällor"),
    ("inline_file_text", "Dokument från användare i chatten"),
    ("knowledge", "Kunskap"),
    ("groups", "Samlingar"),
    ("websites", "Webbplatser"),
    ("integration_knowledge_list", "Integrationer"),
    ("organization_knowledge", "Organisationskunskap"),
    ("rerank_model_id", "Rankning av träffar"),
    ("mcp_servers", "MCP-servrar"),
    ("mcp_tools", "Verktyg"),
    ("attachments", "Bilagor"),
    ("completion_model", "Chattmodell"),
    ("completion_model_kwargs", "Modellbeteende"),
    ("completion_model_kwargs.temperature", "Temperatur"),
    ("completion_model_kwargs.reasoning_effort", "Resonemangsnivå"),
    ("completion_model_kwargs.verbosity", "Detaljnivå"),
    ("completion_model_kwargs.top_p", "Top P"),
    ("completion_model_kwargs.presence_penalty", "Närvarostraff"),
    ("completion_model_kwargs.frequency_penalty", "Frekvensstraff"),
    ("completion_model_kwargs.top_k", "Top K"),
    ("enabled_capabilities", "Funktioner"),
    *((f"{_FUNCTION_REFERENCE_PREFIX}{key}", name) for key, name, _ in FUNCTIONS),
    ("document_template", "Dokumentmall"),
    ("data_retention_days", "Gallring av konversationshistorik"),
    ("published", "Status"),
    ("insight_enabled", "Insikter"),
    ("section:general", "Allmänt"),
    ("section:instructions", "Instruktioner"),
    ("section:knowledge", "Kunskap"),
    ("section:skills", "Skills"),
    ("section:mcp", "MCP-servrar"),
    ("section:attachments", "Bilagor"),
    ("section:ai", "AI-inställningar"),
    ("section:capabilities", "Funktioner"),
    ("section:security", "Säkerhet och integritet"),
    ("section:api-keys", "API-nycklar"),
    ("section:widget", "Webbwidget"),
    ("section:publishing", "Publicering"),
)

_NAME = dict(SETTING_NAMES)

# The editor's sections, in its order, as a reference names them.
_SECTIONS = tuple(key for key, _ in SETTING_NAMES if key.startswith("section:"))

# What a setting reference can name, and what each key is. The editor's
# frontend lists the same keys (SETTING_REFERENCE_KEYS in
# frontend/apps/web-next/src/features/assistants/editor/setting-references.ts);
# a test on each side holds its list to the same written-out one, so change
# both together.
SETTING_REFERENCES: tuple[tuple[str, str], ...] = (
    ("name", f"the name ({_NAME['name']})"),
    ("description", f"the description ({_NAME['description']})"),
    ("prompt", f"the instructions ({_NAME['prompt']})"),
    ("knowledge_mode", "when the knowledge is searched"),
    ("inline_file_text", "how files uploaded in a chat are read"),
    ("knowledge", "the knowledge sources the assistant uses"),
    (
        "rerank_model_id",
        f"the ranking of search results ({_NAME['rerank_model_id']})",
    ),
    ("mcp_servers", "the MCP servers"),
    ("attachments", "the attachments"),
    ("completion_model", f"the chat model ({_NAME['completion_model']})"),
    (
        "completion_model_kwargs",
        f"how the model behaves ({_NAME['completion_model_kwargs']})",
    ),
    ("completion_model_kwargs.reasoning_effort", "the reasoning level"),
    ("completion_model_kwargs.verbosity", "how long the answers are"),
    ("completion_model_kwargs.top_p", "the model's top_p setting"),
    ("completion_model_kwargs.presence_penalty", "the presence penalty"),
    ("completion_model_kwargs.frequency_penalty", "the frequency penalty"),
    ("completion_model_kwargs.top_k", "the model's top_k setting"),
    ("enabled_capabilities", f"the functions ({_NAME['enabled_capabilities']})"),
    *(
        (
            f"{_FUNCTION_REFERENCE_PREFIX}{key}",
            f"the function {name} in {_NAME['enabled_capabilities']}",
        )
        for key, name, _ in FUNCTIONS
    ),
    ("document_template", "the document template generated documents use"),
    ("data_retention_days", "how long conversations are kept"),
    ("published", "whether the assistant is published"),
    ("insight_enabled", f"whether insights are on ({_NAME['insight_enabled']})"),
    *((key, f"the whole of {_NAME[key]}") for key in _SECTIONS),
)

SETTING_REFERENCE_KEYS: tuple[str, ...] = tuple(key for key, _ in SETTING_REFERENCES)

SETTING_REFERENCE_PARAGRAPH = """The person may point at a setting or a part of the editor as
@[name](setting:key): the name is what the editor shows and the key says which
one, and it means that setting or part as the form shows it now. When you name
a setting in an answer, you may write it the same way, with the name the editor
shows and one of the keys below, so the person can press it to see the setting
in the form. This is the one place a key may appear: the editor draws the
reference as a button and never shows the key. When an answer is about one
function, name that function by its name and point at it with its own
reference, such as @[Diagram](setting:enabled_capabilities.charts), never at
the whole of Funktioner as if that were the function's name. Point at
@[Funktioner](setting:enabled_capabilities) only for the list of functions as
a whole. Use only these keys:
""" + "".join(f"- {key}: {what}\n" for key, what in SETTING_REFERENCES)

ASSISTANT_INSTRUCTIONS = (
    HELPER_BASICS
    + "\n"
    + ASSISTANT_FRAGMENT
    + "\n"
    + SETTING_REFERENCE_PARAGRAPH
    + "\n"
    + PROMPT_WRITING
)
