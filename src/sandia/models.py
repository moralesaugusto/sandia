from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str  # "admin" | "operator" | "viewer"
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_login: datetime | None = None
    theme: str = "dark"  # "dark" | "light"


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    username: str
    action: str
    detail: str
    success: bool
    ip_address: str


class AiSettings(SQLModel, table=True):
    # Single row (id=1): the Ollama server backing the AI assistant.
    id: int | None = Field(default=None, primary_key=True)
    ollama_url: str = ""
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.ollama_url and self.model)
