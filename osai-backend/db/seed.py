from db.repositories import seed_demo_data
from db.session import SessionLocal


def main() -> None:
    with SessionLocal() as session:
        seed_demo_data(session)
    print("Seeded demo org, admin user, connector records, and connector accounts.")


if __name__ == "__main__":
    main()
