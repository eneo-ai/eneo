from __future__ import annotations

from intric.services.output_parsing.output_parser import PydanticOutputParser


def test_pydantic_output_parser_builds_and_parses_object_schema():
    parser = PydanticOutputParser(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["name", "count"],
        }
    )

    parsed = parser.parse('{"name":"Flow","count":2}')

    assert parsed.to_value() == {"name": "Flow", "count": 2}
    assert "name" in parser.get_format_instructions()
