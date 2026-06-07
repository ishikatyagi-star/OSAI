import asyncio

from db.repositories import index_seeded_chunks_to_qdrant, seed_rich_demo_data
from db.session import SessionLocal


def main() -> None:
    with SessionLocal() as session:
        seed_rich_demo_data(session)
    print("Seeded database with OSAI rich demo data.")

    print("Indexing mock chunks to Qdrant vector store...")
    try:
        asyncio.run(index_seeded_chunks_to_qdrant())
        print("Indexed chunks to Qdrant successfully.")
    except Exception as exc:
        print(f"Warning: Failed to index to Qdrant ({exc}). Make sure Qdrant is running.")


if __name__ == "__main__":
    main()

