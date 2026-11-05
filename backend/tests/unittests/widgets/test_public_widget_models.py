import pytest
from pydantic import ValidationError

from eneo.widgets.presentation.public_widget_models import WidgetFeedback


def test_feedback_comment_is_bounded():
    assert WidgetFeedback(value=1, text="x" * 2000).text is not None
    with pytest.raises(ValidationError):
        WidgetFeedback(value=1, text="x" * 2001)


def test_feedback_rejects_unknown_fields_and_values():
    with pytest.raises(ValidationError):
        WidgetFeedback(value=0)
    with pytest.raises(ValidationError):
        WidgetFeedback(value=1, rating=5)  # type: ignore[call-arg]
