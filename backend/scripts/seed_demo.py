from pathlib import Path

from youhuo.database import Database


def main() -> None:
    path = Path("data/youhuo.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    db.seed_demo()
    print(f"Seeded demo database: {path.resolve()}")
    db.close()


if __name__ == "__main__":
    main()
