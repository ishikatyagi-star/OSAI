"""Resource-bounded extraction for untrusted direct uploads."""

from __future__ import annotations

import io
import sys
import zipfile
from collections.abc import Iterable
from typing import Literal

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_EXTRACTED_TEXT_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 250
MAX_DOCX_MEMBERS = 512
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
PARSER_MEMORY_BYTES = 256 * 1024 * 1024

ExtractionStatus = Literal["ok", "unsupported", "invalid", "limit"]


class _LimitExceeded(ValueError):
    pass


def _limit_worker_memory() -> None:
    """Cap the isolated parser worker on Linux; the parent still enforces a timeout."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        candidates = [PARSER_MEMORY_BYTES]
        if soft != resource.RLIM_INFINITY:
            candidates.append(soft)
        if hard != resource.RLIM_INFINITY:
            candidates.append(hard)
        target = min(candidates)
        resource.setrlimit(resource.RLIMIT_AS, (target, target))
    except (OSError, ValueError):
        # Process isolation and the parent-side kill timeout still apply when a
        # host does not permit lowering RLIMIT_AS.
        return


def _bounded_join(parts: Iterable[str], separator: str) -> str:
    output: list[str] = []
    total_bytes = 0
    separator_bytes = len(separator.encode())
    for part in parts:
        part_bytes = len(part.encode())
        total_bytes += part_bytes + (separator_bytes if output else 0)
        if total_bytes > MAX_EXTRACTED_TEXT_BYTES:
            raise _LimitExceeded("Extracted text exceeds 2 MB limit")
        output.append(part)
    return separator.join(output)


def _validate_docx_archive(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > MAX_DOCX_MEMBERS:
            raise _LimitExceeded(f"DOCX exceeds {MAX_DOCX_MEMBERS} archive member limit")
        if len({member.filename for member in members}) != len(members):
            raise _LimitExceeded("DOCX contains duplicate archive members")
        expanded_bytes = sum(member.file_size for member in members)
        if expanded_bytes > MAX_DOCX_EXPANDED_BYTES:
            raise _LimitExceeded("DOCX expanded content exceeds 50 MB limit")


def extract_document_text(filename: str, data: bytes) -> tuple[ExtractionStatus, str]:
    """Parse one untrusted document inside the caller's isolated worker process."""
    if len(data) > MAX_FILE_BYTES:
        return "limit", "File exceeds 15 MB limit"

    name = filename.casefold()
    if name.endswith((".txt", ".md", ".markdown", ".csv", ".log")):
        text = data.decode("utf-8", errors="replace")
        if len(text.encode("utf-8")) > MAX_EXTRACTED_TEXT_BYTES:
            return "limit", "Extracted text exceeds 2 MB limit"
        return "ok", text
    if not name.endswith((".pdf", ".docx")):
        return (
            "unsupported",
            "Unsupported file type. Supported: .txt, .md, .csv, .log, .pdf, .docx",
        )

    _limit_worker_memory()
    kind = "PDF" if name.endswith(".pdf") else "DOCX"
    try:
        if kind == "PDF":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise _LimitExceeded(f"PDF exceeds {MAX_PDF_PAGES} page limit")
            text = _bounded_join((page.extract_text() or "" for page in reader.pages), "\n\n")
        else:
            from docx import Document

            _validate_docx_archive(data)
            document = Document(io.BytesIO(data))
            text = _bounded_join((paragraph.text for paragraph in document.paragraphs), "\n")
    except _LimitExceeded as exc:
        return "limit", str(exc)
    except MemoryError:
        return "limit", f"{kind} exceeded parser memory limit"
    except Exception:  # noqa: BLE001 - malformed untrusted documents are client errors
        return "invalid", f"Could not parse {kind}"
    return "ok", text
