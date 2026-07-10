from api.schemas.connector import SourceDocument
from memory.chunker import chunk_document


def test_chunks_keep_boundary_overlap() -> None:
    document = SourceDocument(
        source_id="org:source:1",
        source_type="notion",
        org_id="org",
        external_id="1",
        title="Document",
        text="abcdefghij",
    )
    chunks = chunk_document(document, max_chars=6, overlap_chars=2)
    assert [chunk["text"] for chunk in chunks] == ["abcdef", "efghij", "ij"]
