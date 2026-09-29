from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    """One job board to crawl: a company on a given ATS, or a generic careers page."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("ats", "slug", name="uq_source_ats_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    ats: Mapped[str] = mapped_column(String(40), index=True)
    slug: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered_by: Mapped[str] = mapped_column(String(40), default="seed")
    kind: Mapped[str] = mapped_column(String(20), default="employer")  # employer | agency | aggregator
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_nl_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    postings: Mapped[list["Posting"]] = relationship(back_populates="source")


class Posting(Base):
    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_posting_source_external"),
        Index("ix_posting_dedup", "dedup_key"),
        Index("ix_posting_first_seen", "first_seen"),
        Index("ix_posting_open", "closed_at", "is_tech"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(200), index=True)
    location_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    dedup_key: Mapped[str] = mapped_column(String(64))
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("postings.id"), nullable=True)
    is_tech: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tech_score: Mapped[float | None] = mapped_column(nullable=True)
    extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    extracted_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    link_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok | gone | redirected | error
    valid_through: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # employer's own expiry date

    source: Mapped[Source] = relationship(back_populates="postings")


class Meta(Base):
    """Small key/value table: the data version that tells API processes to reload, and similar flags."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sources_total: Mapped[int] = mapped_column(Integer, default=0)
    sources_ok: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    postings_seen: Mapped[int] = mapped_column(Integer, default=0)
    postings_new: Mapped[int] = mapped_column(Integer, default=0)
    postings_closed: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    """An account: an e-mail address, nothing else. Login is passwordless (a one-time link)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    lang: Mapped[str] = mapped_column(String(2), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LoginToken(Base):
    """A one-time login link. Only the SHA-256 of the token is stored, so a database leak cannot log anyone in."""

    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserData(Base):
    """What a signed-in user keeps across devices: the profile and the saved jobs, as sent by the page."""

    __tablename__ = "user_data"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    saved: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
