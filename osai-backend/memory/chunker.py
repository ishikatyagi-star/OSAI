from api.schemas.connector import SourceDocument


def chunk_document(
    document: SourceDocument, max_chars: int = 4000, overlap_chars: int = 400
) -> list[dict[str, object]]:
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    chunks: list[dict[str, object]] = []
    step = max_chars - overlap_chars
    for index, start in enumerate(range(0, len(document.text), step)):
        text = document.text[start : start + max_chars]
        chunks.append(
            {
                "chunk_id": f"{document.source_id}:{index}",
                "chunk_index": index,
                "source_document_id": document.source_id,
                "org_id": document.org_id,
                "source_type": document.source_type,
                "text": text,
                "content_preview": text[:240],
                "permissions": document.permissions,
                "data_tier": document.data_tier,
                "metadata": {"title": document.title, "url": document.url},
            }
        )
    return chunks
