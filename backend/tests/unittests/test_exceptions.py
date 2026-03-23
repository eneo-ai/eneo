from intric.main.exceptions import QueryException


class TestQueryException:
    def test_with_token_data(self):
        exc = QueryException(tokens_used=45000, token_limit=30000)

        assert "45,000 tokens used" in str(exc)
        assert "limit is 30,000 tokens" in str(exc)
        assert exc.details == {"tokens_used": 45000, "token_limit": 30000}

    def test_no_args_gives_generic_message(self):
        exc = QueryException()

        assert str(exc) == "Query too long"
        assert exc.details == {}

    def test_custom_message_preserved(self):
        exc = QueryException("custom error")

        assert str(exc) == "custom error"
        assert exc.details == {}

    def test_partial_token_data(self):
        exc = QueryException(tokens_used=5000)

        assert str(exc) == "Query too long"
        assert exc.details == {"tokens_used": 5000}
