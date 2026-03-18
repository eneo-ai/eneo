import abc
import json
from abc import abstractmethod

from langchain_core.output_parsers import (
    NumberedListOutputParser,
    PydanticOutputParser as LangchainPydanticOutputParser,
)

from intric.services.output_parsing.pydantic_model_factory import (
    PydanticModelFactory,
)


class ParsedOutput(abc.ABC):
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output

    @abstractmethod
    def to_string(self) -> str:
        raise NotImplementedError

    def to_value(self):
        return self.parsed_output


class OutputParserBase(abc.ABC):
    @abstractmethod
    def parse(self, text) -> ParsedOutput:
        raise NotImplementedError

    @abstractmethod
    def get_format_instructions(self) -> str:
        raise NotImplementedError


class ListOutput(ParsedOutput):
    def to_string(self):
        return json.dumps(self.parsed_output)


class PydanticOutput(ParsedOutput):
    def to_string(self):
        return self.parsed_output.json()

    def to_value(self):
        return self.parsed_output.model_dump()


class TextOutput(ParsedOutput):
    def to_string(self):
        return self.parsed_output


class ListOutputParser(OutputParserBase):
    def __init__(self):
        self.output_parser = NumberedListOutputParser()

    def parse(self, text):
        parsed = self.output_parser.parse(text)

        return ListOutput(parsed)

    def get_format_instructions(self):
        return self.output_parser.get_format_instructions()


class PydanticOutputParser(OutputParserBase):
    def __init__(self, schema):
        self.factory = PydanticModelFactory(schema)
        Model = self.factory.create_pydantic_model()
        self.output_parser = LangchainPydanticOutputParser(pydantic_object=Model)

    def parse(self, text):
        parsed = self.output_parser.parse(text)

        return PydanticOutput(parsed)

    def get_format_instructions(self):
        return self.factory.get_format_instructions()


class TextOutputParser(OutputParserBase):
    def parse(self, text):
        return TextOutput(text)

    def get_format_instructions(self):
        return ""
