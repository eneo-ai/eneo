import json
from enum import Enum
from typing import Annotated

from pydantic import Field, create_model

from eneo.main.exceptions import ValidationException

PYDANTIC_FORMAT_INSTRUCTIONS = """The output should be formatted as a JSON instance that conforms to the JSON schema below.

As an example, for the schema {{"properties": {{"foo": {{"title": "Foo", "description": "a list of strings", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}} the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of the schema. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.

Here is the output schema:
```
{schema}
```"""  # noqa


class JSONSchema(str, Enum):
    OBJECT = "object"
    PROPERTIES = "properties"
    TYPE = "type"
    ITEMS = "items"
    DESCRIPTION = "description"


class JSONTypes(str, Enum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"


TYPES = {
    JSONTypes.STRING: str,
    JSONTypes.NUMBER: float,
    JSONTypes.INTEGER: int,
    JSONTypes.ARRAY: list,
    JSONTypes.BOOLEAN: bool,
}

MODEL_NAME = "DynamicPydanticModel"


class PydanticModelFactory:
    def __init__(self, schema: dict):
        self.schema = schema
        self._model_fields = {}

    def validate_schema(self):
        try:
            self.create_pydantic_model()
        except Exception as e:
            raise ValidationException("Not a valid JSON Schema") from e

    def _create_nested(self, schema, field, description, is_list=False):
        level = PydanticModelFactory(schema)
        model = level.create_pydantic_model()

        if is_list:
            self._create_field(list[model], field, description)
        else:
            self._create_field(model, field, description)

    def _create_field(self, factory, field, description):
        self._model_fields[field] = (
            Annotated[factory, Field(default_factory=factory, description=description)],
            ...,
        )

    def create_pydantic_model(self):
        for name, prop in self.schema[JSONSchema.PROPERTIES].items():
            description = prop.get(JSONSchema.DESCRIPTION)
            if prop[JSONSchema.TYPE] == JSONSchema.OBJECT:
                self._create_nested(prop, name, description)

            elif prop[JSONSchema.TYPE] == JSONTypes.ARRAY:
                items = prop.get(JSONSchema.ITEMS)
                type = items[JSONSchema.TYPE]
                if type == JSONSchema.OBJECT:
                    self._create_nested(items, name, description, is_list=True)
                else:
                    self._create_field(list[TYPES[type]], name, description)

            else:
                self._create_field(TYPES[prop[JSONSchema.TYPE]], name, description)

        return create_model(MODEL_NAME, **self._model_fields)

    def get_format_instructions(self):
        reduced_schema = self.schema

        if JSONSchema.TYPE in reduced_schema:
            del reduced_schema[JSONSchema.TYPE]

        schema_str = json.dumps(reduced_schema)

        return PYDANTIC_FORMAT_INSTRUCTIONS.format(schema=schema_str)
