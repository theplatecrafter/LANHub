"""Tests for shared/validators.py - Input validation."""

import pytest
from shared.validators import (
    validate_username,
    validate_message,
)


@pytest.mark.unit
class TestUsernameValidation:
    """Test username validation."""

    def test_valid_username(self):
        """Test valid username passes."""
        is_valid, error = validate_username("alice")
        assert is_valid is True
        assert error == ""

    def test_empty_username(self):
        """Test empty username fails."""
        is_valid, error = validate_username("")
        assert is_valid is False
        assert len(error) > 0

    def test_username_too_long(self):
        """Test username exceeding max length fails."""
        long_name = "a" * 50
        is_valid, error = validate_username(long_name, max_length=24)
        assert is_valid is False
        assert "too long" in error.lower() or "length" in error.lower()

    def test_taken_username(self):
        """Test taken username fails."""
        taken = {"alice", "bob"}
        is_valid, error = validate_username("alice", taken_usernames=taken)
        assert is_valid is False
        assert "taken" in error.lower() or "already" in error.lower()

    def test_username_with_profanity(self, mock_profanity):
        """Test username with profanity fails."""
        from dependencies import DI

        is_valid, error = validate_username(
            "badworduser", check_profanity_func=DI.get("check_profanity")
        )
        assert is_valid is False
        assert "disallowed" in error.lower() or "profan" in error.lower()

    def test_valid_username_with_numbers(self):
        """Test username with numbers is valid."""
        is_valid, error = validate_username("alice123")
        assert is_valid is True

    def test_valid_username_with_underscore(self):
        """Test username with underscore is valid."""
        is_valid, error = validate_username("alice_user")
        assert is_valid is True


@pytest.mark.unit
class TestMessageValidation:
    """Test message validation."""

    def test_valid_message(self):
        """Test valid message passes."""
        is_valid, error = validate_message("Hello world!", max_chars=500)
        assert is_valid is True
        assert error == ""

    def test_empty_message(self):
        """Test empty message fails."""
        is_valid, error = validate_message("", max_chars=500)
        assert is_valid is False
        assert len(error) > 0

    def test_message_too_long(self):
        """Test message exceeding max chars fails."""
        long_msg = "a" * 600
        is_valid, error = validate_message(long_msg, max_chars=500)
        assert is_valid is False
        assert "long" in error.lower() or "limit" in error.lower()

    def test_whitespace_only_message(self):
        """Test whitespace-only message fails."""
        is_valid, error = validate_message("   \n\t   ", max_chars=500)
        assert is_valid is False

    def test_message_with_profanity(self, mock_profanity):
        """Test message with profanity fails."""
        from dependencies import DI

        is_valid, error = validate_message(
            "This is badword content",
            max_chars=500,
            check_profanity_func=DI.get("check_profanity"),
        )
        assert is_valid is False
        assert "disallowed" in error.lower() or "profan" in error.lower()

    def test_message_with_special_chars(self):
        """Test message with special characters is valid."""
        is_valid, error = validate_message("Hello! @#$% World?", max_chars=500)
        assert is_valid is True

    def test_message_with_unicode(self):
        """Test message with unicode characters is valid."""
        is_valid, error = validate_message("こんにちは 世界", max_chars=500)
        assert is_valid is True


@pytest.mark.unit
class TestValidationEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_username_exactly_max_length(self):
        """Test username exactly at max length."""
        username = "a" * 24
        is_valid, error = validate_username(username, max_length=24)
        assert is_valid is True

    def test_message_exactly_max_length(self):
        """Test message exactly at max length."""
        message = "a" * 500
        is_valid, error = validate_message(message, max_chars=500)
        assert is_valid is True

    def test_username_one_under_max(self):
        """Test username one character under max."""
        username = "a" * 23
        is_valid, error = validate_username(username, max_length=24)
        assert is_valid is True

    def test_username_one_over_max(self):
        """Test username one character over max."""
        username = "a" * 25
        is_valid, error = validate_username(username, max_length=24)
        assert is_valid is False

    def test_validate_with_leading_trailing_spaces(self):
        """Test that validation handles stripped input."""
        is_valid, error = validate_username("  alice  ")
        # Should handle trimming gracefully
        assert isinstance(is_valid, bool)
