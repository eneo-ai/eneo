from typing_extensions import override

from intric.services.output_parsing.output_parser import (
    OutputParserBase,
    ParsedOutput,
)

FORMAT_INSTRUCTIONS = (
    "If the question relates to normal conversation or"
    " if the answer to the user question can be found anywhere in the"
    " articles delimited by triple quotes, or is relevant"
    ' to any of the information in the articles delimited by triple quotes, answer "YES",'
    ' otherwise answer "NO". Answer only "YES" or "NO".'
)


class BooleanOutput(ParsedOutput):
    @override
    def to_string(self) -> str:
        return str(self.parsed_output)


class BooleanGuardOutputParser(OutputParserBase):
    def __init__(self) -> None:
        super().__init__()
        self.true_val = "YES"
        self.false_val = "NO"

    @override
    def parse(self, text: str) -> BooleanOutput:
        cleaned_text = text.strip()

        return BooleanOutput(cleaned_text.upper() == self.true_val)

    @override
    def get_format_instructions(self) -> str:
        return FORMAT_INSTRUCTIONS
