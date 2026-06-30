from eneo.workflows.filters import ContinuationFilter


def test_cont_filter_filter_on_true():
    cont_filter = ContinuationFilter(continue_on=False)
    assert cont_filter.filter(False)
    assert not cont_filter.filter(True)


def test_cont_filter_filter_on_false():
    cont_filter = ContinuationFilter()
    assert cont_filter.filter(True)
    assert not cont_filter.filter(False)


def test_cont_filter_fail_value():
    fail_string = "Sorry I can not answer that."
    cont_filter = ContinuationFilter(chain_breaker_message=fail_string)

    cont = cont_filter.filter(False)

    assert cont.chain_breaker_message == fail_string
