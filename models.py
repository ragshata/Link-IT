# models.py
from datetime import datetime

from sqlalchemy import BigInteger, String, Text, DateTime, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    avatar_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stack: Mapped[str | None] = mapped_column(String(256), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(128), nullable=True)
    skills: Mapped[str | None] = mapped_column(String(256), nullable=True)
    goals: Mapped[str | None] = mapped_column(String(256), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Profile tg={self.telegram_id} role={self.role}>"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)

    title: Mapped[str] = mapped_column(String(200))
    stack: Mapped[str | None] = mapped_column(String(256), nullable=True)
    idea: Mapped[str] = mapped_column(Text)

    looking_for_role: Mapped[str | None] = mapped_column(String(256), nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extra: Mapped[str | None] = mapped_column(String(256), nullable=True)

    image_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} owner={self.owner_telegram_id} title={self.title!r}>"


class ConnectionRequest(Base):
    __tablename__ = "connection_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    from_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    to_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)

    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending / accepted / rejected

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ConnectionRequest id={self.id} from={self.from_telegram_id} "
            f"to={self.to_telegram_id} status={self.status}>"
        )
