import pytest

from eneo.main.exceptions import ValidationException
from eneo.services.output_parsing.pydantic_model_factory import (
    PydanticModelFactory,
)


def test_validate_schema():
    schema = {"type": "object", "properties": {"hello"}}

    with pytest.raises(ValidationException, match="Not a valid JSON Schema"):
        PydanticModelFactory(schema).validate_schema()


def test_create_simpel_model():
    schema = {
        "type": "object",
        "properties": {
            "string": {
                "type": "string",
                "description": "name description",
            },
            "integer": {
                "type": "integer",
                "description": "address description",
            },
            "boolean": {
                "type": "boolean",
                "description": "boolean description",
            },
        },
    }

    example_object = {"string": "string", "integer": 1, "boolean": True}

    model_factory = PydanticModelFactory(schema)
    model = model_factory.create_pydantic_model()
    model_instance = model(**example_object)

    assert model_instance.string == example_object["string"]
    assert model_instance.integer == example_object["integer"]
    assert model_instance.boolean == example_object["boolean"]


def test_create_model_with_list():
    schema = {
        "type": "object",
        "properties": {
            "list": {
                "type": "array",
                "description": "some description",
                "items": {"type": "string"},
            },
        },
    }

    example_object = {"list": ["item_1", "item_2", "item_3"]}

    model_factory = PydanticModelFactory(schema)
    model = model_factory.create_pydantic_model()
    model_instance = model(**example_object)

    assert model_instance.list == example_object["list"]


def test_create_nested_model():
    schema = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "description": "some description",
                "properties": {
                    "nested_1": {
                        "type": "string",
                        "description": "nested_1 description",
                    },
                    "nested_2": {
                        "type": "string",
                        "description": "nested_2 description",
                    },
                },
            },
        },
    }

    example_object = {"nested": {"nested_1": "nested_1", "nested_2": "nested_2"}}

    model_factory = PydanticModelFactory(schema)
    model = model_factory.create_pydantic_model()
    model_instance = model(**example_object)

    assert model_instance.nested.model_dump() == example_object["nested"]


def test_validate_model_with_list():
    schema = {
        "type": "object",
        "properties": {
            "classes": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "The most relevant classes, ordered from most relevant to least"
                    " relevant. At most 3 classes, but could be less"
                ),
            },
            "motivation": {
                "type": "string",
                "description": "A short motivation for the classification",
            },
        },
    }

    example_object = {"classes": [1, 2, 3], "motivation": "Hurr durr"}
    also_valid = {"classes": [1, "2", 3], "motivation": "hurr furr"}

    model_factory = PydanticModelFactory(schema)
    model = model_factory.create_pydantic_model()
    model_instance = model(**example_object)
    also_valid_model_instance = model(**also_valid)

    assert model_instance.classes == [1, 2, 3]
    assert also_valid_model_instance.classes == [1, 2, 3]


def test_validate_model_with_list_of_objects():
    schema = {
        "type": "object",
        "properties": {
            "likelihoods": {
                "type": "array",
                "description": "The array of likelihoods",
                "items": {
                    "type": "object",
                    "description": "The likelihood for a single comparison",
                    "properties": {
                        "likelihood_of_confusion": {
                            "type": "number",
                            "description": (
                                "The likelihood of confusion score, on a scale from 1 to 3, "
                                "where 3 is high likelihood of confusion, and 1 is low"
                            ),
                        },
                        "motivation": {
                            "type": "string",
                            "description": "the motivation for the likelihood score",
                        },
                    },
                },
            }
        },
    }

    example_object = {
        "likelihoods": [
            {"likelihood_of_confusion": 3, "motivation": "Ouff not looking too good"}
        ]
    }

    model_factory = PydanticModelFactory(schema)
    model = model_factory.create_pydantic_model()
    model_instance = model(**example_object)

    assert model_instance.likelihoods[0].likelihood_of_confusion == 3
