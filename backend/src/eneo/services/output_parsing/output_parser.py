import abc
import json
from abc import abstractmethod
from typing import Protocol, cast

from langchain_core import output_parsers
from pydantic import BaseModel
from typing_extensions import override

from eneo.services.output_parsing.pydantic_model_factory import (
    JSONSchemaDefinition,
    PydanticModelFactory,
)


class SupportsListParsing(Protocol):
    def parse(self, text: str) -> list[str]: ...

    def get_format_instructions(self) -> str: ...


class SupportsPydanticParsing(Protocol):
    def parse(self, text: str) -> BaseModel: ...

    def get_format_instructions(self) -> str: ...


class ParsedOutput(abc.ABC):
    def __init__(self, parsed_output: object) -> None:
        super().__init__()
        self.parsed_output = parsed_output

    @abstractmethod
    def to_string(self) -> str:
        raise NotImplementedError

    def to_value(self) -> object:
        return self.parsed_output


class OutputParserBase(abc.ABC):
    @abstractmethod
    def parse(self, text: str) -> ParsedOutput:
        raise NotImplementedError

    @abstractmethod
    def get_format_instructions(self) -> str:
        raise NotImplementedError


class ListOutput(ParsedOutput):
    @override
    def to_string(self) -> str:
        return json.dumps(cast(list[str], self.parsed_output))


class PydanticOutput(ParsedOutput):
    @override
    def to_string(self) -> str:
        return cast(BaseModel, self.parsed_output).model_dump_json()

    @override
    def to_value(self) -> dict[str, object]:
        return cast(dict[str, object], cast(BaseModel, self.parsed_output).model_dump())


class TextOutput(ParsedOutput):
    @override
    def to_string(self) -> str:
        return cast(str, self.parsed_output)


class ListOutputParser(OutputParserBase):
    def __init__(self) -> None:
        super().__init__()
        self.output_parser = cast(
            SupportsListParsing, output_parsers.NumberedListOutputParser()
        )

    @override
    def parse(self, text: str) -> ListOutput:
        parsed = self.output_parser.parse(text)

        return ListOutput(parsed)

    @override
    def get_format_instructions(self) -> str:
        return self.output_parser.get_format_instructions()


class PydanticOutputParser(OutputParserBase):
    def __init__(self, schema: JSONSchemaDefinition) -> None:
        super().__init__()
        self.factory = PydanticModelFactory(schema)
        model = self.factory.create_pydantic_model()
        self.output_parser = cast(
            SupportsPydanticParsing,
            output_parsers.PydanticOutputParser(pydantic_object=model),
        )

    @override
    def parse(self, text: str) -> PydanticOutput:
        parsed = self.output_parser.parse(text)

        return PydanticOutput(parsed)

    @override
    def get_format_instructions(self) -> str:
        return self.factory.get_format_instructions()


class TextOutputParser(OutputParserBase):
    @override
    def parse(self, text: str) -> TextOutput:
        return TextOutput(text)

    @override
    def get_format_instructions(self) -> str:
        return ""
