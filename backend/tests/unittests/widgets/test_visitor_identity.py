from types import SimpleNamespace
from uuid import uuid4

from eneo.widgets.application.visitor_identity import VisitorIdentity
from eneo.widgets.domain.widget import Widget


def _widget(**overrides):
    return Widget.model_validate(
        {
            "id": uuid4(),
            "public_id": "wgt_" + "A" * 22,
            "tenant_id": uuid4(),
            "space_id": uuid4(),
            "target_id": uuid4(),
            "name": "Test",
            **overrides,
        }
    )


def _identity(secret: str = "signing-key") -> VisitorIdentity:
    return VisitorIdentity(settings=SimpleNamespace(url_signing_key=secret))  # type: ignore[arg-type]


def test_key_is_stable_and_verifies():
    widget = _widget()
    visitor = uuid4()
    identity = _identity()
    key = identity.key_for(widget, visitor)
    assert key == identity.key_for(widget, visitor)
    assert identity.verify(widget, visitor, key)
    assert identity.resolve(widget, visitor, key) == visitor


def test_key_is_bound_to_widget_and_deployment():
    visitor = uuid4()
    widget = _widget()
    key = _identity().key_for(widget, visitor)
    assert not _identity().verify(_widget(), visitor, key)
    assert not _identity("other-key").verify(widget, visitor, key)


def test_bad_or_missing_key_issues_a_fresh_id():
    widget = _widget()
    claimed = uuid4()
    identity = _identity()
    assert identity.resolve(widget, claimed, None) != claimed
    assert identity.resolve(widget, claimed, "00" * 32) != claimed
    assert identity.resolve(widget, None, None) is not None
