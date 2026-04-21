import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence
from uuid import UUID

from typing_extensions import override

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
from intric.tokens.token_utils import (
    count_tokens,  # noqa: F401 — re-exported for external callers
)

MIN_PERCENTAGE_KNOWLEDGE = (
    0.8  # Strive towards a minimum of 80% of the context as knowledge
)


class _InfoBlobChunkLike(Protocol):
    text: str
    chunk_no: int
    info_blob_id: UUID
    info_blob_title: str | None


class _InformationChunkLike(Protocol):
    id: UUID
    title: str
    content: str


def _build_files_string(files: list[File]) -> str:
    if files:
        # Use json.dumps() to properly escape special characters in filenames and text
        # This prevents broken JSON if the content contains quotes or other special chars
        files_string = "\n".join(
            json.dumps({"filename": file.name, "text": file.text}) for file in files
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
    id: UUID
    title: str
    start_chunk: int
    end_chunk: int
    content: str
    chunk_count: int
    relevance_score: float = 0.0


class _Prompt:
    def __init__(self, version: int = 1, model_name: str = ""):
        super().__init__()
        self.prompt: str | None = None
        self.knowledge: str | None = None
        self.web_search_result: str | None = None
        self.attachments: str | None = None
        self._knowledge_tokens: int = 0
        self.version: int = version
        self.model_name: str = model_name

    @override
    def __str__(self):
        components: list[str] = []

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
    def _common_overlap(text1: str, text2: str) -> int:
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

    def _join_overlapping_text(self, chunks: list[_InfoBlobChunkLike]) -> str:
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
        chunks: list[_InfoBlobChunkLike],
        max_tokens: int,
    ) -> str:
        # Create a dictionary to store chunk indices
        chunk_indices = {id(chunk): i for i, chunk in enumerate(chunks)}

        # Group chunks by info_blob
        chunks_by_info_blob: dict[UUID, list[_InfoBlobChunkLike]] = {}
        used_tokens = 0
        for chunk in chunks:
            chunk_tokens = count_tokens(chunk.text, self.model_name)

            if chunks_by_info_blob.get(chunk.info_blob_id) is None:
                chunks_by_info_blob[chunk.info_blob_id] = []

                # Count the tokens for the metadata
                chunk_tokens += count_tokens(
                    '"""source_title: {}, source_id: {}\n"""'.format(
                        chunk.info_blob_title, str(chunk.info_blob_id)[:8]
                    ),
                    self.model_name,
                )

            if chunk_tokens + used_tokens > max_tokens:
                break

            chunks_by_info_blob[chunk.info_blob_id].append(chunk)
            used_tokens += chunk_tokens

        # Save the used_tokens for later
        self._knowledge_tokens = used_tokens

        # Process each document
        chunk_groupings: list[ChunkGrouping] = []
        grouping_scores: defaultdict[int, float] = defaultdict(float)

        for doc_id, doc_chunks in chunks_by_info_blob.items():
            # Edgecase if the first chunk of a new info-blob is the cutoff point
            if not doc_chunks:
                continue

            # Sort chunks by their order in the original document
            doc_chunks.sort(key=lambda x: x.chunk_no)

            # Group coherent chunks
            coherent_groups: list[list[_InfoBlobChunkLike]] = []
            current_group: list[_InfoBlobChunkLike] = [doc_chunks[0]]

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
                    title=group[0].info_blob_title or "",
                    start_chunk=group[0].chunk_no,
                    end_chunk=group[-1].chunk_no,
                    content=full_text,
                    chunk_count=len(group),
                )

                # Calculate score based on the position of chunks in the original input
                score = sum(1.0 / (chunk_indices[id(chunk)] + 1) for chunk in group)
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

        raise ValueError(f"Unsupported prompt version: {self.version}")

    @staticmethod
    def _create_information_string(
        information_chunks: Sequence[_InformationChunkLike] | None = None,
    ) -> str:
        if information_chunks is None:
            information_chunks = []
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
    def num_tokens(self) -> int:
        return count_tokens(str(self), self.model_name)

    def add_prompt(self, prompt: str, transcription: bool) -> None:
        if transcription and not prompt:
            prompt = TRANSCRIPTION_PROMPT

        self.prompt = prompt

    def add_web_search_result(
        self, web_search_results: Sequence[_InformationChunkLike] | None = None
    ) -> None:
        if web_search_results is None:
            web_search_results = []
        self.web_search_result = self._create_information_string(
            information_chunks=web_search_results
        )

    def add_knowledge(
        self, chunks: Sequence[_InfoBlobChunkLike], max_tokens: int
    ) -> None:
        if not chunks:
            return

        chunk_list = list(chunks)
        self.knowledge = self._reconstruct_and_order_chunks(
            chunks=chunk_list,
            max_tokens=max_tokens - self.num_tokens,
        )

    def add_attachments(self, files: list[File]) -> None:
        self.attachments = _build_files_string(files=files)

    def get_tokens_of_knowledge(self) -> int:
        return self._knowledge_tokens


class ContextBuilder:
    @staticmethod
    def _functions() -> list[FunctionDefinition]:
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
        files: list[File] | None = None,
        transcription_inputs: list[str] | None = None,
    ) -> str:
        if files is None:
            files = []
        if transcription_inputs is None:
            transcription_inputs = []
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
    def _get_files_by_type(files: list[File], file_type: FileType) -> list[File]:
        return [file for file in files if file.file_type == file_type]

    def _build_messages(
        self,
        session: Optional[SessionInDB],
        max_tokens: int,
        min_len: int = 3,
        model_name: str = "",
    ) -> tuple[list[Message], int]:
        if session is None:
            return [], 0

        messages: list[Message] = []
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

            message_tokens = count_tokens(question, model_name) + count_tokens(
                answer, model_name
            )

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
        model_name: str = "",
        files: list[File] | None = None,
        prompt: str = "",
        prompt_files: list[File] | None = None,
        transcription_inputs: list[str] | None = None,
        info_blob_chunks: Sequence[_InfoBlobChunkLike] | None = None,
        session: Optional[SessionInDB] = None,
        version: int = 1,
        use_image_generation: bool = False,
        web_search_results: Sequence[_InformationChunkLike] | None = None,
        mcp_tools: list[FunctionDefinition] | None = None,
    ) -> Context:
        if files is None:
            files = []
        if prompt_files is None:
            prompt_files = []
        if transcription_inputs is None:
            transcription_inputs = []
        if info_blob_chunks is None:
            info_blob_chunks = []
        if web_search_results is None:
            web_search_results = []
        if mcp_tools is None:
            mcp_tools = []
        tokens_used = 0

        # Create the input, count the tokens.
        _input_string = self._build_input(
            input_str=input_str,
            files=self._get_files_by_type(files, FileType.TEXT),
            transcription_inputs=transcription_inputs,
        )
        tokens_used_input = count_tokens(_input_string, model_name)
        tokens_used += tokens_used_input

        # Create the necessary parts of the prompt.
        # Add the tokens used.
        _prompt = _Prompt(version=version, model_name=model_name)
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

        # Create the messages. When knowledge chunks are present, reserve 80%
        # for knowledge and cap history to 20%. When there are no chunks the
        # full remaining budget goes to history.
        if info_blob_chunks:
            max_tokens_messages = (
                int(max_tokens * (1 - MIN_PERCENTAGE_KNOWLEDGE)) - tokens_used
            )
        else:
            max_tokens_messages = max_tokens - tokens_used
        messages, tokens_used_messages = self._build_messages(
            session=session,
            max_tokens=max_tokens_messages,
            min_len=3,
            model_name=model_name,
        )
        tokens_used += tokens_used_messages

        # Check for worst case.
        # Up until this point, all text will be
        # assumed by the user to be there,
        # and erroring is preferable to not
        # including something.
        if tokens_used > max_tokens:
            raise QueryException(tokens_used=tokens_used, token_limit=max_tokens)

        # Add the knowledge in all the space that is left.
        tokens_left = max_tokens - tokens_used
        _prompt.add_knowledge(chunks=info_blob_chunks, max_tokens=tokens_left)
        prompt_text = str(_prompt)
        tokens_used += _prompt.get_tokens_of_knowledge()

        # Combine image generation tools with MCP tools
        functions: list[FunctionDefinition] = []
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
