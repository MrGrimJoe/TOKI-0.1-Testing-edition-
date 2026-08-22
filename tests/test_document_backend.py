"""
test_document_backend.py -- exercises document_backend.py against a REAL
pandoc binary (installed in this sandbox via apt, not mocked/stubbed) to
verify actual docx/html/rtf conversion, plus the bundled-vs-PATH pandoc
discovery order added to close the installer's open pandoc question.
"""
import shutil
import stat
from pathlib import Path

import pytest

from conversion_engine.backends import document_backend as db

PANDOC_AVAILABLE = shutil.which("pandoc") is not None


@pytest.fixture(autouse=True)
def _clean_bundled_dir(monkeypatch, tmp_path):
    # Point BUNDLED_DIR at a scratch directory per test so tests can't
    # see each other's fake binaries and can't see a real bundled pandoc
    # if one is ever actually shipped alongside this checkout.
    fake_bundled = tmp_path / "bin" / "pandoc"
    monkeypatch.setattr(db, "BUNDLED_DIR", fake_bundled)
    yield


class TestPandocDiscovery:
    def test_falls_back_to_path_when_not_bundled(self, monkeypatch):
        # No bundled binary exists (scratch dir is empty) -> must resolve
        # via PATH, same as before the bundled-lookup feature existed.
        # PATH is mocked here (rather than relying on a real pandoc
        # install) so this test doesn't depend on the machine it runs on
        # -- unlike TestRealConversion below, this one isn't gated by
        # PANDOC_AVAILABLE and must pass on a machine with no pandoc at all.
        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/to/pandoc")
        found = db._require_pandoc()
        assert found == "/fake/path/to/pandoc"

    def test_prefers_bundled_binary_over_path(self, monkeypatch):
        bundled = db._bundled_pandoc_path()
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text("#!/bin/sh\necho fake-bundled-pandoc\n")
        bundled.chmod(bundled.stat().st_mode | stat.S_IEXEC)

        found = db._require_pandoc()
        assert found == str(bundled)
        assert found != shutil.which("pandoc")

    def test_missing_everywhere_raises_actionable_error(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(db.PandocNotFoundError, match="pandoc.org"):
            db._require_pandoc()


@pytest.mark.skipif(not PANDOC_AVAILABLE, reason="pandoc not on PATH")
class TestRealConversion:
    def test_markdown_to_docx(self, tmp_path):
        src = tmp_path / "notes.md"
        src.write_text("# Title\n\nSome **bold** text.\n", encoding="utf-8")

        out = db.convert(str(src), "docx")

        assert Path(out).exists()
        assert Path(out).suffix == ".docx"
        assert Path(out).stat().st_size > 0
        assert Path(out).name == "notes_converted.docx"  # doesn't overwrite src
        assert src.exists()

    def test_docx_to_html_round_trip(self, tmp_path):
        md_src = tmp_path / "doc.md"
        md_src.write_text("# Heading\n\nBody text here.\n", encoding="utf-8")
        docx_path = db.convert(str(md_src), "docx")

        html_out = db.convert(docx_path, "html")

        content = Path(html_out).read_text(encoding="utf-8")
        assert "Heading" in content
        assert "Body text here" in content

    def test_overwrite_true_replaces_original_extension_in_place(self, tmp_path):
        src = tmp_path / "note.md"
        src.write_text("# Hi\n", encoding="utf-8")
        out = db.convert(str(src), "html", overwrite=True)
        assert Path(out) == src.with_suffix(".html")

    def test_from_pdf_raises_not_implemented(self, tmp_path):
        fake_pdf = tmp_path / "scan.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        with pytest.raises(NotImplementedError, match="pdf"):
            db.convert(str(fake_pdf), "docx")

    def test_markdown_to_pdf_real_conversion(self, tmp_path):
        # Real, unmocked pandoc + LaTeX toolchain -- this is the exact
        # phrasing/format pair that surfaced the missing-LaTeX gap this
        # session ("turn this .md file into a pdf"). Verifies the happy
        # path actually produces a real PDF when the toolchain IS present.
        src = tmp_path / "notes.md"
        src.write_text("# Hello\n\nA real markdown file.\n", encoding="utf-8")
        out = db.convert(str(src), "pdf")
        assert Path(out).exists()
        assert Path(out).read_bytes()[:5] == b"%PDF-"


class TestMissingPdfEngine:
    """Found live this session: on a machine with pandoc but no LaTeX
    toolchain, converting to PDF raised a raw multi-line LaTeX error
    ("! LaTeX Error: File `lmodern.sty' not found.") straight through to
    the caller -- FileConvertAPI.convert_selected()'s generic
    `except Exception as e: return f"...: {e}"` would have shown that
    verbatim to the user. Mocks the pandoc subprocess call (rather than
    actually uninstalling the system's LaTeX packages) to reproduce that
    exact stderr shape and confirm it's now caught and turned into a
    clear, actionable PdfEngineNotFoundError instead."""

    def test_missing_latex_toolchain_raises_clear_error(self, tmp_path, monkeypatch):
        src = tmp_path / "notes.md"
        src.write_text("# Hi\n", encoding="utf-8")

        class _FakeResult:
            returncode = 1
            stderr = (
                "Error producing PDF.\n"
                "! LaTeX Error: File `lmodern.sty' not found.\n"
            )

        monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _FakeResult())
        with pytest.raises(db.PdfEngineNotFoundError, match="MiKTeX"):
            db.convert(str(src), "pdf")

    def test_missing_pdflatex_binary_raises_clear_error(self, tmp_path, monkeypatch):
        src = tmp_path / "notes.md"
        src.write_text("# Hi\n", encoding="utf-8")

        class _FakeResult:
            returncode = 1
            stderr = "pdflatex not found. Please select a different --pdf-engine."

        monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _FakeResult())
        with pytest.raises(db.PdfEngineNotFoundError, match="MiKTeX"):
            db.convert(str(src), "pdf")

    def test_non_pdf_pandoc_failure_still_uses_generic_error(self, tmp_path, monkeypatch):
        # The narrow marker check must only fire for target_ext == "pdf"
        # -- an unrelated pandoc failure converting to, say, docx should
        # keep surfacing the existing generic RuntimeError, unchanged.
        src = tmp_path / "notes.md"
        src.write_text("# Hi\n", encoding="utf-8")

        class _FakeResult:
            returncode = 1
            stderr = "some unrelated docx conversion failure"

        monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _FakeResult())
        with pytest.raises(RuntimeError) as exc_info:
            db.convert(str(src), "docx")
        assert not isinstance(exc_info.value, db.PdfEngineNotFoundError)

    def test_unrelated_pdf_failure_still_uses_generic_error(self, tmp_path, monkeypatch):
        # A PDF-target failure for a reason unrelated to a missing LaTeX
        # toolchain must not be mistakenly caught by the narrow marker
        # check either.
        src = tmp_path / "notes.md"
        src.write_text("# Hi\n", encoding="utf-8")

        class _FakeResult:
            returncode = 1
            stderr = "some completely unrelated pandoc failure"

        monkeypatch.setattr(db.subprocess, "run", lambda *a, **k: _FakeResult())
        with pytest.raises(RuntimeError) as exc_info:
            db.convert(str(src), "pdf")
        assert not isinstance(exc_info.value, db.PdfEngineNotFoundError)

    def test_bad_pandoc_run_raises_clear_error(self, tmp_path):
        # A source pandoc genuinely can't parse (garbage docx bytes) should
        # surface pandoc's own stderr, not a bare stack trace or silent
        # empty output.
        bad = tmp_path / "broken.docx"
        bad.write_bytes(b"not a real docx file")
        with pytest.raises(RuntimeError, match="pandoc conversion failed"):
            db.convert(str(bad), "html")
