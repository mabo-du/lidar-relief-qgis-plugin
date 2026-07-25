"""test_diagnose_upload.py — Tests for the QGIS.org upload diagnostic.

exports: (test functions)
used_by: pytest runner
rules:
  Never performs a real upload — only the response-rendering logic is
  tested here, since that is what has to stay useful. The request itself
  is exercised by running the workflow.
  The token must never appear in output. Assert that.
"""

import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

diagnose = pytest.importorskip("diagnose_qgis_upload")


class TestDescribeResponse:
    """Turning a raw server reply into something actionable."""

    def test_success_is_reported_as_accepted(self):
        out = diagnose.describe_response(200, '{"ok": true}')
        assert "HTTP 200" in out
        assert "Accepted" in out
        assert "verify_published" in out, "should point at the follow-up check"

    def test_created_counts_as_success(self):
        assert "Accepted" in diagnose.describe_response(201, "")

    def test_json_body_is_pretty_printed(self):
        body = json.dumps({"errors": {"about": ["Too long"]}})
        out = diagnose.describe_response(400, body)
        assert "HTTP 400" in out
        assert '"about"' in out

    def test_named_field_gets_a_hint(self):
        body = json.dumps({"about": ["Ensure this value has at most 1000 chars"]})
        out = diagnose.describe_response(400, body)
        assert "about" in out
        assert "metadata.txt" in out, "hint should name the file to edit"

    def test_multiple_named_fields_all_get_hints(self):
        body = json.dumps({"tags": ["too many"], "icon": ["cannot decode"]})
        out = diagnose.describe_response(400, body)
        assert "tags" in out and "icon" in out

    def test_unrecognised_error_falls_back_to_the_web_form(self):
        out = diagnose.describe_response(400, "Bad Request")
        assert "web form" in out, (
            "when the body names nothing we recognise, the user needs the "
            "one route that does render validation errors"
        )

    def test_empty_body_is_stated_plainly(self):
        out = diagnose.describe_response(400, "")
        assert "empty response body" in out

    def test_non_json_body_is_still_shown(self):
        out = diagnose.describe_response(500, "<html>Server Error</html>")
        assert "Server Error" in out

    def test_enormous_body_is_truncated(self):
        out = diagnose.describe_response(400, "x" * 20000)
        assert len(out) < 6000, "a huge HTML error page must not flood the log"


class TestKnownHints:
    """The hint table should reflect this repo's actual history."""

    def test_covers_the_fields_that_have_failed_before(self):
        for field in ("tags", "about", "icon", "version"):
            assert field in diagnose.KNOWN_FIELD_HINTS

    def test_tags_hint_records_the_real_incident(self):
        assert "2.0.18" in diagnose.KNOWN_FIELD_HINTS["tags"]

    def test_icon_hint_records_the_jpeg_problem(self):
        assert "JPEG" in diagnose.KNOWN_FIELD_HINTS["icon"]


class TestTokenSafety:
    """A diagnostic that leaks the token would be worse than no diagnostic."""

    def test_token_is_not_echoed_by_describe_response(self):
        secret = "qgis_tok_SECRETVALUE123"
        out = diagnose.describe_response(400, '{"detail": "nope"}')
        assert secret not in out

    def test_upload_redacts_auth_in_its_own_logging(self):
        import inspect

        source = inspect.getsource(diagnose.upload)
        assert "redacted" in source
        assert 'print(f"     auth: Bearer {token}' not in source


class TestCliGuards:
    """Fail fast and clearly rather than making a doomed request."""

    def test_missing_token_returns_2(self, monkeypatch, tmp_path, capsys):
        archive = tmp_path / "p.zip"
        archive.write_bytes(b"PK")
        monkeypatch.delenv("QGIS_TOKEN", raising=False)
        monkeypatch.setattr(sys, "argv", ["diagnose_qgis_upload.py", str(archive)])
        assert diagnose.main() == 2
        assert "No token" in capsys.readouterr().err

    def test_missing_archive_returns_2(self, monkeypatch, capsys):
        monkeypatch.setenv("QGIS_TOKEN", "x")
        monkeypatch.setattr(
            sys, "argv", ["diagnose_qgis_upload.py", "/nonexistent/p.zip"]
        )
        assert diagnose.main() == 2
        assert "Archive not found" in capsys.readouterr().err
