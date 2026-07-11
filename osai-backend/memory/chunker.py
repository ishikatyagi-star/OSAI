from api.schemas.connector import SourceDocument


def chunk_document(document: SourceDocument, max_chars: int = 4000) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for index, start in enumerate(range(0, len(document.text), max_chars)):
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
                "department_id": document.department_id,
                "metadata": {"title": document.title, "url": document.url},
            }
        )
    return chunks
