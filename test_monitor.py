"""Tests for URL monitor."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import monitor


@pytest.fixture
def temp_state_file(tmp_path):
    """Use a temporary state file for tests."""
    state_file = tmp_path / "data" / "previous_content.json"
    original_state_file = monitor.STATE_FILE
    monitor.STATE_FILE = state_file
    yield state_file
    monitor.STATE_FILE = original_state_file


@pytest.fixture
def mock_html_response():
    """Create a mock HTML response."""
    def _make_response(body_text):
        return f"""
        <html>
        <head><title>Test</title></head>
        <body>
            <nav>Navigation</nav>
            <main>{body_text}</main>
            <footer>Footer</footer>
        </body>
        </html>
        """
    return _make_response


class TestFetchPageText:
    """Tests for fetch_page_text function."""

    def test_extracts_body_text(self, mock_html_response):
        """Should extract text from body, excluding nav/footer."""
        html = mock_html_response("Hello World")

        with patch("monitor.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = monitor.fetch_page_text("http://example.com")

            assert "Hello World" in result
            assert "Navigation" not in result
            assert "Footer" not in result

    def test_normalizes_whitespace(self, mock_html_response):
        """Should normalize multiple newlines and strip whitespace."""
        html = mock_html_response("Line 1\n\n\n\nLine 2")

        with patch("monitor.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = monitor.fetch_page_text("http://example.com")

            # Should not have excessive blank lines
            assert "\n\n\n" not in result


class TestStateManagement:
    """Tests for state load/save functions."""

    def test_load_empty_state(self, temp_state_file):
        """Should return empty dict when no state file exists."""
        result = monitor.load_previous_state()
        assert result == {}

    def test_save_and_load_state(self, temp_state_file):
        """Should save and load state correctly."""
        state = {"page1": "content1", "page2": "content2"}
        monitor.save_state(state)

        loaded = monitor.load_previous_state()
        assert loaded == state


class TestGenerateDiff:
    """Tests for diff generation."""

    def test_generates_diff_for_changes(self):
        """Should generate unified diff showing changes."""
        old = "Line 1\nLine 2\nLine 3"
        new = "Line 1\nLine 2 modified\nLine 3"

        diff = monitor.generate_diff(old, new)

        assert "-Line 2" in diff
        assert "+Line 2 modified" in diff

    def test_empty_diff_for_identical_content(self):
        """Should generate empty diff for identical content."""
        text = "Same content"
        diff = monitor.generate_diff(text, text)
        assert diff == ""


class TestCheckForChanges:
    """Tests for the main change detection logic."""

    def test_first_run_stores_baseline(self, temp_state_file, mock_html_response):
        """First run should store content without detecting changes."""
        html = mock_html_response("Initial content")

        with patch("monitor.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            changes = monitor.check_for_changes()

            assert changes == []
            assert temp_state_file.exists()

    def test_detects_content_change(self, temp_state_file, mock_html_response):
        """Should detect when page content changes."""
        # Set up initial state
        monitor.save_state({
            "HudsonsBay": "Old content for HBC",
            "TRUCanada": "Old content for TRU",
        })

        new_html = mock_html_response("New content - UPDATED!")

        with patch("monitor.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = new_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            changes = monitor.check_for_changes()

            # Both pages should show changes
            assert len(changes) == 2
            assert changes[0]["name"] in ["HudsonsBay", "TRUCanada"]
            assert "diff" in changes[0]
            assert "timestamp" in changes[0]

    def test_no_changes_when_content_same(self, temp_state_file, mock_html_response):
        """Should not detect changes when content is identical."""
        html = mock_html_response("Same content")

        with patch("monitor.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            # First run - baseline
            monitor.check_for_changes()

            # Second run - same content
            changes = monitor.check_for_changes()

            assert changes == []


class TestEmailNotification:
    """Tests for email sending."""

    def test_email_sent_on_change(self, temp_state_file, mock_html_response):
        """Should send email when changes are detected."""
        # Set up initial state with old content
        monitor.save_state({
            "HudsonsBay": "Old HBC content",
            "TRUCanada": "Old TRU content",
        })

        new_html = mock_html_response("Brand new content!")

        with patch("monitor.requests.get") as mock_get, \
             patch("monitor.send_email_gmail") as mock_email, \
             patch.dict(os.environ, {"GMAIL_ADDRESS": "test@gmail.com", "GMAIL_APP_PASSWORD": "fake"}):

            mock_response = MagicMock()
            mock_response.text = new_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            monitor.main()

            # Email should be called for each changed page
            assert mock_email.call_count == 2

    def test_no_email_when_no_changes(self, temp_state_file, mock_html_response):
        """Should not send email when no changes detected."""
        html = mock_html_response("Unchanged content")

        with patch("monitor.requests.get") as mock_get, \
             patch("monitor.send_email_gmail") as mock_email:

            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            # First run - baseline
            monitor.check_for_changes()

            # Second run - no changes
            monitor.main()

            mock_email.assert_not_called()

    def test_email_contains_diff(self, temp_state_file, mock_html_response):
        """Email body should contain the diff of changes."""
        monitor.save_state({"HudsonsBay": "Old content", "TRUCanada": "Old content"})

        new_html = mock_html_response("New content here")

        with patch("monitor.requests.get") as mock_get, \
             patch("monitor.send_email_gmail") as mock_email:

            mock_response = MagicMock()
            mock_response.text = new_html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            monitor.main()

            # Check the email body contains diff markers
            call_args = mock_email.call_args_list[0]
            email_body = call_args[0][1]  # Second positional arg is body
            assert "-Old content" in email_body or "+New content" in email_body


class TestGmailFunction:
    """Tests for Gmail sending function."""

    def test_prints_message_when_no_credentials(self, capsys):
        """Should print message when Gmail credentials missing."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GMAIL_ADDRESS", None)
            os.environ.pop("GMAIL_APP_PASSWORD", None)

            monitor.send_email_gmail("Test Subject", "Test Body")

            captured = capsys.readouterr()
            assert "ERROR" in captured.out
            assert "GMAIL_ADDRESS" in captured.out

    def test_sends_email_with_credentials(self):
        """Should attempt to send email when credentials provided."""
        with patch.dict(os.environ, {
            "GMAIL_ADDRESS": "test@gmail.com",
            "GMAIL_APP_PASSWORD": "testpass"
        }), patch("monitor.smtplib.SMTP_SSL") as mock_smtp:

            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            monitor.send_email_gmail("Test Subject", "Test Body")

            mock_server.login.assert_called_once_with("test@gmail.com", "testpass")
            mock_server.sendmail.assert_called_once()


class TestIntegrationLivePages:
    """
    Integration tests that fetch real pages.
    These tests hit the actual URLs to verify the full flow works.
    """

    @pytest.fixture
    def live_state_file(self, tmp_path):
        """Use a temporary state file for integration tests."""
        state_file = tmp_path / "data" / "previous_content.json"
        original_state_file = monitor.STATE_FILE
        monitor.STATE_FILE = state_file
        yield state_file
        monitor.STATE_FILE = original_state_file

    def test_can_fetch_live_hudsons_bay_page(self):
        """Verify we can fetch and parse the real HudsonsBay page."""
        url = "https://www.alvarezandmarsal.com/HudsonsBay"
        content = monitor.fetch_page_text(url)

        # Should have substantial content
        assert len(content) > 100
        # Should contain some expected text (company name or related terms)
        content_lower = content.lower()
        assert "hudson" in content_lower or "bay" in content_lower or "alvarez" in content_lower

    def test_can_fetch_live_tru_canada_page(self):
        """Verify we can fetch and parse the real TRUCanada page."""
        url = "https://www.alvarezandmarsal.com/TRUCanada"
        content = monitor.fetch_page_text(url)

        # Should have substantial content
        assert len(content) > 100
        # Should contain some expected text
        content_lower = content.lower()
        assert "tru" in content_lower or "canada" in content_lower or "alvarez" in content_lower

    def test_live_pages_no_change_on_consecutive_runs(self, live_state_file):
        """Fetching live pages twice should detect no changes."""
        # First run - establish baseline
        changes_first = monitor.check_for_changes()
        assert changes_first == []  # First run never detects changes

        # Second run - should detect no changes (pages haven't changed)
        changes_second = monitor.check_for_changes()
        assert changes_second == []

    def test_live_pages_detect_simulated_change(self, live_state_file):
        """
        Simulate a change by storing fake previous content,
        then verify the monitor detects the 'change' when fetching live pages.
        """
        # Store fake "previous" content that differs from the real pages
        monitor.save_state({
            "HudsonsBay": "This is fake old content that won't match the real page.",
            "TRUCanada": "This is also fake old content for TRU Canada page.",
        })

        # Now check for changes - should detect both pages as "changed"
        changes = monitor.check_for_changes()

        assert len(changes) == 2

        # Verify change details
        change_names = {c["name"] for c in changes}
        assert "HudsonsBay" in change_names
        assert "TRUCanada" in change_names

        # Each change should have a diff showing the difference
        for change in changes:
            assert "diff" in change
            assert len(change["diff"]) > 0
            assert "url" in change
            assert "timestamp" in change

    def test_live_change_triggers_email_attempt(self, live_state_file, capsys):
        """
        Full integration: simulate change on live pages and verify email is triggered.
        Email sending is mocked to avoid actually sending.
        """
        # Store fake previous content
        monitor.save_state({
            "HudsonsBay": "Old fake content",
            "TRUCanada": "Old fake content",
        })

        email_calls = []

        def capture_email(subject, body, html_body=None):
            email_calls.append({"subject": subject, "body": body, "html_body": html_body})
            print(f"EMAIL CAPTURED: {subject}")

        # Patch only the email function, let real HTTP requests happen
        with patch("monitor.send_email_gmail", side_effect=capture_email):
            monitor.main()

        # Should have attempted to send 2 emails (one per page)
        assert len(email_calls) == 2

        # Verify email content
        for email in email_calls:
            assert "URL Change Detected" in email["subject"]
            assert "change was detected" in email["body"].lower()
            # Should contain diff markers
            assert "---" in email["body"] or "+++" in email["body"]
            # Should have HTML version
            assert email["html_body"] is not None
            assert "<html>" in email["html_body"]
            assert "Change Detected" in email["html_body"]

        # Check console output
        captured = capsys.readouterr()
        assert "CHANGE DETECTED" in captured.out
        assert "EMAIL CAPTURED" in captured.out

    def test_live_no_change_no_email(self, live_state_file):
        """
        Full integration: when live pages haven't changed, no email should be sent.
        """
        # First run to establish baseline with real content
        monitor.check_for_changes()

        email_calls = []

        def capture_email(subject, body):
            email_calls.append({"subject": subject, "body": body})

        # Second run - no changes expected
        with patch("monitor.send_email_gmail", side_effect=capture_email):
            monitor.main()

        # No emails should be sent
        assert len(email_calls) == 0
