from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import tiktoken

from intric.ai_models.completion_models.completion_model import (
    Context,
    FunctionDefinition,
    Message,
)
from intric.completion_models.infrastructure.static_prompts import (
    HALLUCINATION_GUARD,
    SHOW_REFERENCES_PROMPT,
    TRANSCRIPTION_PROMPT,
)
from intric.files.file_models import File, FileType
from intric.main.exceptions import QueryException
from intric.sessions.session import SessionInDB

if TYPE_CHECKING:
    from uuid import UUID

    from intric.completion_models.infrastructure.web_search import WebSearchResult
    from intric.info_blobs.info_blob import InfoBlobChunkInDBWithScore

CONTEXT_SIZE_BUFFER = 1000  # Counting tokens is not an exakt science, leave some buffer
MIN_PERCENTAGE_KNOWLEDGE = (
    0.8  # Strive towards a minimum of 80% of the context as knowledge
)

# Cache tiktoken encoder to avoid expensive re-instantiation on every call
_TIKTOKEN_ENCODING = None


def count_tokens(text: str):
    global _TIKTOKEN_ENCODING
    # ensure we're always passing a string to the encoder
    if text is None:
        return 0
    if _TIKTOKEN_ENCODING is None:
        _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    return len(_TIKTOKEN_ENCODING.encode(text))


def _build_files_string(files: list[File]):
    if files:
        files_string = "\n".join(
            f'{{"filename": "{file.name}", "text": "{file.text}"}}' for file in files
        )

        return (
            "Below are files uploaded by the user. "
            "You should act like you can see the files themselves, "
            "and not reveal the specific formatting "
            "you see below:"
            f"\n\n{files_string}"
        )

    return ""


@dataclass
class ChunkGrouping:
    id: "UUID"
    title: str
    start_chunk: int
    end_chunk: int
    content: str
    chunk_count: int
    relevance_score: Optional[float] = None


class _Prompt:
    def __init__(self, version: int = 1):
        self.prompt = None
        self.knowledge = None
        self.web_search_result = None
        self.attachments = None
        self._knowledge_tokens = 0
        self.version = version

    def __str__(self):
        components = []

        if self.prompt:
            components.append(self.prompt)

        # Add references prompt if either knowledge or web search results exist
        # but only for version 2
        if (self.knowledge or self.web_search_result) and self.version == 2:
            components.append(SHOW_REFERENCES_PROMPT)

        # Add hallucination guard for version 1 knowledge
        if self.knowledge and self.version == 1:
            components.append(HALLUCINATION_GUARD)

        if self.knowledge:
            components.append(self.knowledge)

        if self.web_search_result:
            components.append(self.web_search_result)

        if self.attachments:
            components.append(self.attachments)

        return "\n\n".join(components)

    @staticmethod
    def _common_overlap(text1: str, text2: str):
        # Cache the text lengths to prevent multiple calls.
        text1_length = len(text1)
        text2_length = len(text2)
        # Eliminate the null case.
        if text1_length == 0 or text2_length == 0:
            return 0
        # Truncate the longer string.
        if text1_length > text2_length:
            text1 = text1[-text2_length:]
        elif text1_length < text2_length:
            text2 = text2[:text1_length]
        # Quick check for the worst case.
        if text1 == text2:
            return min(text1_length, text2_length)

        # Start by looking for a single character match
        # and increase length until no match is found.
        best = 0
        length = 1
        while True:
            pattern = text1[-length:]
            found = text2.find(pattern)
            if found == -1:
                return best
            length += found
            if text1[-length:] == text2[:length]:
                best = length
                length += 1

    def _join_overlapping_text(self, chunks: list["InfoBlobChunkInDBWithScore"]):
        if not chunks:
            return ""

        result_string = chunks[0].text

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1].text
            current_chunk = chunks[i].text

            overlap = self._common_overlap(prev_chunk, current_chunk)

            result_string = f"{result_string}{current_chunk[overlap:]}"

        return result_string

    def _reconstruct_and_order_chunks(
        self,
        chunks: list["InfoBlobChunkInDBWithScore"],
        max_tokens: int,
    ):
        # Create a dictionary to store chunk indices
        chunk_indices = {id(chunk): i for i, chunk in enumerate(chunks)}

        # Group chunks by info_blob
        chunks_by_info_blob = {}
        used_tokens = 0
        for chunk in chunks:
            chunk_tokens = count_tokens(chunk.text)

            if chunks_by_info_blob.get(chunk.info_blob_id) is None:
                chunks_by_info_blob[chunk.info_blob_id] = []

                # Count the tokens for the metadata
                chunk_tokens += count_tokens(
                    '"""source_title: {}, source_id: {}\n"""'.format(
                        chunk.info_blob_title, str(chunk.info_blob_id)[:8]
                    )
                )

            if chunk_tokens + used_tokens > max_tokens:
                break

            chunks_by_info_blob[chunk.info_blob_id].append(chunk)
            used_tokens += chunk_tokens

        # Save the used_tokens for later
        self._knowledge_tokens = used_tokens

        # Process each document
        chunk_groupings = []
        grouping_scores = defaultdict(float)

        for doc_id, doc_chunks in chunks_by_info_blob.items():
            # Edgecase if the first chunk of a new info-blob is the cutoff point
            if not doc_chunks:
                continue

            # Sort chunks by their order in the original document
            doc_chunks.sort(key=lambda x: x.chunk_no)

            # Group coherent chunks
            coherent_groups = []
            current_group = [doc_chunks[0]]

            for i in range(1, len(doc_chunks)):
                if doc_chunks[i].chunk_no == current_group[-1].chunk_no + 1:
                    current_group.append(doc_chunks[i])
                else:
                    coherent_groups.append(current_group)
                    current_group = [doc_chunks[i]]

            coherent_groups.append(current_group)

            # Process each coherent group as a separate document
            for group in coherent_groups:
                full_text = self._join_overlapping_text(group)

                chunk_grouping = ChunkGrouping(
                    id=doc_id,
                    title=group[0].info_blob_title,
                    start_chunk=group[0].chunk_no,
                    end_chunk=group[-1].chunk_no,
                    content=full_text,
                    chunk_count=len(group),
                )

                # Calculate score based on the position of chunks in the original input
                score = sum(1 / (chunk_indices[id(chunk)] + 1) for chunk in group)
                grouping_scores[id(chunk_grouping)] = score

                chunk_groupings.append(chunk_grouping)

        # Add scores to documents and sort by score
        for grouping in chunk_groupings:
            grouping.relevance_score = grouping_scores[id(grouping)]

        chunk_groupings.sort(key=lambda x: x.relevance_score, reverse=True)

        if self.version == 1:
            return "\n".join(
                f'"""{chunk_grouping.content}"""' for chunk_grouping in chunk_groupings
            )

        elif self.version == 2:
            return self._create_information_string(information_chunks=chunk_groupings)

    @staticmethod
    def _create_information_string(
        information_chunks: list[ChunkGrouping] | list["WebSearchResult"] = [],
    ):
        if not information_chunks:
            return ""

        return "\n".join(
            '"""source_title: {}, source_id: {}\n{}"""'.format(
                chunk.title,
                str(chunk.id)[:8],
                chunk.content,
            )
            for chunk in information_chunks
        )

    @property
    def num_tokens(self):
        return count_tokens(str(self))

    def add_prompt(
        self,
        prompt: str,
        transcription: bool,
    ):
        if transcription and not prompt:
            prompt = TRANSCRIPTION_PROMPT

        self.prompt = prompt

    def add_web_search_result(self, web_search_results: list["WebSearchResult"] = []):
        self.web_search_result = self._create_information_string(
            information_chunks=web_search_results
        )

    def add_knowledge(
        self, chunks: list["InfoBlobChunkInDBWithScore"], max_tokens: int
    ):
        if not chunks:
            return

        self.knowledge = self._reconstruct_and_order_chunks(
            chunks=chunks,
            max_tokens=max_tokens - self.num_tokens,
        )

    def add_attachments(self, files: list[File]):
        self.attachments = _build_files_string(files=files)

    def get_tokens_of_knowledge(self):
        return self._knowledge_tokens


class ContextBuilder:
    @staticmethod
    def _functions():
        return [
            FunctionDefinition(
                name="generate_image",
                description=(
                    "Generate an image based on a text prompt. Will always be JPEG."
                    "\n\nWhen discussing this ability with users:"
                    "\n- DO NOT mention 'tools' or the technical name 'generate_image'."
                    "\n- DO say you can 'create' or 'generate' images based on descriptions."
                    "\n- Use natural, conversational language about your image capabilities."
                    "\n- If asked to create Vector-based images, do it in code instead."
                ),
                schema={
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                    "required": ["prompt"],
                    "additionalProperties": False,
                },
            )
        ]

    def _build_input(
        self,
        input_str: str,
        files: list[File] = [],
        transcription_inputs: list[str] = [],
    ):
        if files:
            files_string = _build_files_string(files)
            input_str = f"{files_string}\n\n{input_str}"

        if transcription_inputs:
            # For now, transcription is only available for apps,
            # which means that we don't have to worry about what
            # happens with follow-up questions.
            transcription_string = "\n".join(
                map(lambda t: f'transcription: ""{t}""', transcription_inputs)
            )
            input_str = f"{transcription_string}\n\n{input_str}"

        return input_str.strip()

    @staticmethod
    def _get_files_by_type(files: list[File], file_type: FileType):
        return [file for file in files if file.file_type == file_type]

    def _build_messages(
        self, session: Optional[SessionInDB], max_tokens: int, min_len: int = 3
    ):
        if session is None:
            return [], 0

        messages = []
        total_tokens = 0

        for message in reversed(session.questions):
            question = self._build_input(
                message.question,
                self._get_files_by_type(message.files, FileType.TEXT),
            )
            answer = message.answer
            images = self._get_files_by_type(message.files, FileType.IMAGE)
            generated_images = self._get_files_by_type(
                message.generated_files, FileType.IMAGE
            )

            message_tokens = count_tokens(question) + count_tokens(answer)

            if len(messages) > min_len and total_tokens + message_tokens > max_tokens:
                break

            messages.insert(
                0,
                Message(
                    question=question,
                    answer=answer,
                    images=images,
                    generated_images=generated_images,
                ),
            )

            total_tokens += message_tokens

        return messages, total_tokens

    def build_context(
        self,
        input_str: str,
        *,
        max_tokens: int,
        files: list[File] = [],
        prompt: str = "",
        prompt_files: list[File] = [],
        transcription_inputs: list[str] = [],
        info_blob_chunks: list["InfoBlobChunkInDBWithScore"] = [],
        session: Optional[SessionInDB] = None,
        version: int = 1,
        use_image_generation: bool = False,
        web_search_results: list["WebSearchResult"] = [],
        mcp_tools: list[FunctionDefinition] = [],
    ):
        tokens_used = 0
        max_tokens_usable = max_tokens - CONTEXT_SIZE_BUFFER  # Leave some room.

        # Create the input, count the tokens.
        _input_string = self._build_input(
            input_str=input_str,
            files=self._get_files_by_type(files, FileType.TEXT),
            transcription_inputs=transcription_inputs,
        )
        tokens_used_input = count_tokens(_input_string)
        tokens_used += tokens_used_input

        # Create the necessary parts of the prompt.
        # Add the tokens used.
        _prompt = _Prompt(version=version)
        _prompt.add_prompt(
            prompt=prompt,
            transcription=bool(transcription_inputs),
        )
        _prompt.add_attachments(
            files=self._get_files_by_type(prompt_files, FileType.TEXT)
        )
        # Add web search results first so references prompt appears before knowledge
        _prompt.add_web_search_result(web_search_results=web_search_results)
        tokens_used += _prompt.num_tokens

        # Create the messages, keeping within the 80% mark,
        # and minimum 3.
        max_tokens_messages = (
            int(max_tokens_usable * (1 - MIN_PERCENTAGE_KNOWLEDGE)) - tokens_used
        )
        messages, tokens_used_messages = self._build_messages(
            session=session, max_tokens=max_tokens_messages, min_len=3
        )
        tokens_used += tokens_used_messages

        # Check for worst case.
        # Up until this point, all text will be
        # assumed by the user to be there,
        # and erroring is preferable to not
        # including something.
        if tokens_used > max_tokens_usable:
            raise QueryException("Query too long")

        # Add the knowledge in all the space that is left.
        tokens_left = max_tokens_usable - tokens_used
        _prompt.add_knowledge(chunks=info_blob_chunks, max_tokens=tokens_left)
        prompt_text = str(_prompt)
        tokens_used += _prompt.get_tokens_of_knowledge()

        # Combine image generation tools with MCP tools
        functions = []
        if use_image_generation:
            functions.extend(self._functions())
        functions.extend(mcp_tools)

        return Context(
            input=_input_string,
            prompt=prompt_text,
            messages=messages,
            images=self._get_files_by_type(files, FileType.IMAGE),
            token_count=tokens_used,
            function_definitions=functions,
        )
