from app.database.session import Base, engine
from app.models.message import Message


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
