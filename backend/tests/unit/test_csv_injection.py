"""Unit tests for CSV injection prevention in audit service."""

import pytest

from intric.audit.application.audit_service import _sanitize_csv_cell


class TestSanitizeCsvCell:
    """Tests for CSV injection prevention via cell sanitization."""

    # === Formula prefix sanitization tests ===

    def test_sanitize_equals_prefix(self):
        """Values starting with '=' should be prefixed with single quote."""
        assert _sanitize_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
        assert _sanitize_csv_cell("=cmd|' /C calc'!A1") == "'=cmd|' /C calc'!A1"
        assert _sanitize_csv_cell("=1+1") == "'=1+1"

    def test_sanitize_plus_prefix(self):
        """Values starting with '+' should be prefixed with single quote."""
        assert _sanitize_csv_cell("+SUM(A1:A10)") == "'+SUM(A1:A10)"
        assert _sanitize_csv_cell("+cmd") == "'+cmd"
        assert _sanitize_csv_cell("+1") == "'+1"

    def test_sanitize_minus_prefix(self):
        """Values starting with '-' should be prefixed with single quote."""
        assert _sanitize_csv_cell("-SUM(A1:A10)") == "'-SUM(A1:A10)"
        assert _sanitize_csv_cell("-1+1") == "'-1+1"
        assert _sanitize_csv_cell("-@cmd") == "'-@cmd"

    def test_sanitize_at_prefix(self):
        """Values starting with '@' should be prefixed with single quote."""
        assert _sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
        assert _sanitize_csv_cell("@user.email") == "'@user.email"
        assert _sanitize_csv_cell("@@user") == "'@@user"

    def test_sanitize_tab_prefix(self):
        """Values starting with tab character should be prefixed with single quote."""
        assert _sanitize_csv_cell("\tcommand") == "'\tcommand"
        assert _sanitize_csv_cell("\t=SUM()") == "'\t=SUM()"

    def test_sanitize_carriage_return_prefix(self):
        """Values starting with carriage return should be prefixed with single quote."""
        assert _sanitize_csv_cell("\rmalicious") == "'\rmalicious"
        assert _sanitize_csv_cell("\r\ninjection") == "'\r\ninjection"

    # === Safe value tests ===

    def test_sanitize_normal_value_unchanged(self):
        """Normal values without dangerous prefixes should be unchanged."""
        assert _sanitize_csv_cell("Normal text") == "Normal text"
        assert _sanitize_csv_cell("User created assistant") == "User created assistant"
        assert _sanitize_csv_cell("192.168.1.1") == "192.168.1.1"
        assert _sanitize_csv_cell("test@example.com") == "test@example.com"

    def test_sanitize_empty_string(self):
        """Empty string should return unchanged."""
        assert _sanitize_csv_cell("") == ""

    def test_sanitize_none_handling(self):
        """None should be handled gracefully - function expects str but code uses 'value and'."""
        # The function checks 'if value' first, so empty/falsy values pass through
        # But None would fail on value[0], so callers should handle None externally
        # This test documents the expected behavior when called with empty string
        assert _sanitize_csv_cell("") == ""

    def test_sanitize_dangerous_char_not_at_start(self):
        """Dangerous characters not at position 0 should not trigger sanitization."""
        assert _sanitize_csv_cell("sum=total") == "sum=total"
        assert _sanitize_csv_cell("result+1") == "result+1"
        assert _sanitize_csv_cell("delta-10") == "delta-10"
        assert _sanitize_csv_cell("email@domain.com") == "email@domain.com"
        assert _sanitize_csv_cell("before\tafter") == "before\tafter"

    def test_sanitize_multiple_dangerous_chars(self):
        """Only first character matters for sanitization."""
        assert _sanitize_csv_cell("=+@-test") == "'=+@-test"
        assert _sanitize_csv_cell("+-@=test") == "'+-@=test"

    def test_sanitize_unicode_prefix(self):
        """Unicode characters at start should not trigger sanitization."""
        assert _sanitize_csv_cell("日本語") == "日本語"
        assert _sanitize_csv_cell("émoji") == "émoji"
        assert _sanitize_csv_cell("Ñoño") == "Ñoño"

    def test_sanitize_number_prefix(self):
        """Numbers at start should not trigger sanitization."""
        assert _sanitize_csv_cell("123") == "123"
        assert _sanitize_csv_cell("42 is the answer") == "42 is the answer"
        assert _sanitize_csv_cell("0.5") == "0.5"

    def test_sanitize_preserves_internal_content(self):
        """Sanitization should only add prefix, not modify internal content."""
        original = "=SUM(A1:A10) + some=text with @mentions"
        sanitized = _sanitize_csv_cell(original)
        assert sanitized == "'" + original
        assert sanitized[1:] == original

    # === Edge case tests ===

    def test_sanitize_single_dangerous_char(self):
        """Single dangerous character should be sanitized."""
        assert _sanitize_csv_cell("=") == "'="
        assert _sanitize_csv_cell("+") == "'+"
        assert _sanitize_csv_cell("-") == "'-"
        assert _sanitize_csv_cell("@") == "'@"

    def test_sanitize_whitespace_only(self):
        """Whitespace-only strings starting with space should be unchanged."""
        assert _sanitize_csv_cell("   ") == "   "
        assert _sanitize_csv_cell(" text") == " text"

    def test_sanitize_newline_not_in_list(self):
        """Newline character is not in the dangerous prefix list."""
        # Note: \n is NOT in the dangerous list, only \r and \t are
        assert _sanitize_csv_cell("\ntext") == "\ntext"

    def test_csv_injection_real_world_attacks(self):
        """Test against real-world CSV injection attack payloads."""
        # DDE (Dynamic Data Exchange) attacks
        assert _sanitize_csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
        assert _sanitize_csv_cell("=HYPERLINK(\"http://evil.com\")") == "'=HYPERLINK(\"http://evil.com\")"

        # Shell command execution via formula
        assert _sanitize_csv_cell("-2+3+cmd|' /C calc'!A0") == "'-2+3+cmd|' /C calc'!A0"
        assert _sanitize_csv_cell("@SUM(1+1)*cmd|' /C calc'!A0") == "'@SUM(1+1)*cmd|' /C calc'!A0"

        # Tab-separated injection
        assert _sanitize_csv_cell("\t=1+1") == "'\t=1+1"
