from intric.services.output_parsing.boolean_guard_output_parser import (
    BooleanGuardOutputParser,
)
from intric.services.output_parsing.output_parser import (
    ListOutputParser,
    OutputParserBase,
    PydanticOutputParser,
    TextOutputParser,
)
from intric.services.service import Service


class OutputParserFactory:
    @classmethod
    def create(cls, service: Service) -> OutputParserBase:
        match service.output_format:
            case "json":
                if service.json_schema is None:
                    raise ValueError(
                        "json_schema is required when output_format is 'json'"
                    )
                return PydanticOutputParser(schema=service.json_schema)

            case "list":
                return ListOutputParser()

            case "boolean":
                return BooleanGuardOutputParser()

            case _:
                return TextOutputParser()
