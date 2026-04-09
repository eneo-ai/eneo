import json
from enum import Enum
from typing import Any, Mapping, cast

from pydantic import BaseModel, Field, create_model

from intric.main.exceptions import ValidationException

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


JSONSchemaDefinition = dict[str, object]


TYPES: dict[str, type[object]] = {
    JSONTypes.STRING.value: str,
    JSONTypes.NUMBER.value: float,
    JSONTypes.INTEGER.value: int,
    JSONTypes.BOOLEAN.value: bool,
}

MODEL_NAME = "DynamicPydanticModel"


class PydanticModelFactory:
    def __init__(self, schema: JSONSchemaDefinition) -> None:
        super().__init__()
        self.schema = schema
        self._model_fields: dict[str, tuple[object, object]] = {}

    def validate_schema(self) -> None:
        try:
            self.create_pydantic_model()
        except Exception as e:
            raise ValidationException("Not a valid JSON Schema") from e

    def _get_properties(
        self, schema: Mapping[str, object]
    ) -> dict[str, JSONSchemaDefinition]:
        properties = schema.get(JSONSchema.PROPERTIES.value)
        if not isinstance(properties, dict):
            raise ValidationException("Schema is missing properties")

        typed_properties: dict[str, JSONSchemaDefinition] = {}
        for key, value in cast(dict[str, object], properties).items():
            if not isinstance(value, dict):
                raise ValidationException("Invalid schema property definition")
            typed_properties[key] = cast(JSONSchemaDefinition, value)
        return typed_properties

    def _get_type(self, schema: Mapping[str, object]) -> str:
        schema_type = schema.get(JSONSchema.TYPE.value)
        if not isinstance(schema_type, str):
            raise ValidationException("Schema node is missing type")
        return schema_type

    def _get_description(self, schema: Mapping[str, object]) -> str | None:
        description = schema.get(JSONSchema.DESCRIPTION.value)
        return description if isinstance(description, str) else None

    def _get_items(self, schema: Mapping[str, object]) -> JSONSchemaDefinition:
        items = schema.get(JSONSchema.ITEMS.value)
        if not isinstance(items, dict):
            raise ValidationException("Array schema is missing items")
        return cast(JSONSchemaDefinition, items)

    def _create_nested(
        self,
        schema: JSONSchemaDefinition,
        field: str,
        description: str | None,
        *,
        is_list: bool = False,
    ) -> None:
        level = PydanticModelFactory(schema)
        model = level.create_pydantic_model()
        field_type: object = list[model] if is_list else model

        self._create_field(field_type, field, description)

    def _create_field(
        self, field_type: object, field: str, description: str | None
    ) -> None:
        self._model_fields[field] = (
            field_type,
            Field(..., description=description),
        )

    def create_pydantic_model(self) -> type[BaseModel]:
        for name, prop in self._get_properties(self.schema).items():
            description = self._get_description(prop)
            prop_type = self._get_type(prop)
            if prop_type == JSONSchema.OBJECT.value:
                self._create_nested(prop, name, description)

            elif prop_type == JSONTypes.ARRAY.value:
                items = self._get_items(prop)
                item_type = self._get_type(items)
                if item_type == JSONSchema.OBJECT.value:
                    self._create_nested(items, name, description, is_list=True)
                else:
                    self._create_field(list[TYPES[item_type]], name, description)

            else:
                self._create_field(TYPES[prop_type], name, description)

        return cast(
            type[BaseModel], cast(Any, create_model)(MODEL_NAME, **self._model_fields)
        )

    def get_format_instructions(self) -> str:
        reduced_schema = dict(self.schema)

        if JSONSchema.TYPE.value in reduced_schema:
            del reduced_schema[JSONSchema.TYPE.value]

        schema_str = json.dumps(reduced_schema)

        return PYDANTIC_FORMAT_INSTRUCTIONS.format(schema=schema_str)
