from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    worlds: Mapped[list["World"]] = relationship(back_populates="user")
    stories: Mapped[list["Story"]] = relationship(back_populates="user")


class AuthCredential(Base, TimestampMixin):
    __tablename__ = "auth_credentials"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(320), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_created", "user_id", text("created_at DESC")),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String(160))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    ip_region: Mapped[str | None] = mapped_column(String(160))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthLoginThrottle(Base):
    __tablename__ = "auth_login_throttles"
    __table_args__ = (Index("ix_auth_login_throttles_updated", "updated_at"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthActionToken(Base):
    __tablename__ = "auth_action_tokens"
    __table_args__ = (
        Index(
            "ix_auth_action_tokens_user_purpose_created",
            "user_id",
            "purpose",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class World(Base, TimestampMixin):
    __tablename__ = "worlds"
    __table_args__ = (Index("ix_worlds_user_updated", "user_id", text("updated_at DESC")),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(String(120))
    rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    lorebook: Mapped[list] = mapped_column(JSONB, default=list)
    tone: Mapped[dict] = mapped_column(JSONB, default=dict)

    user: Mapped[User] = relationship(back_populates="worlds")
    characters: Mapped[list["Character"]] = relationship(back_populates="world")
    stories: Mapped[list["Story"]] = relationship(back_populates="world")


class Character(Base, TimestampMixin):
    __tablename__ = "characters"
    __table_args__ = (
        Index("ix_characters_user_world_created", "user_id", "world_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    world_id: Mapped[UUID | None] = mapped_column(ForeignKey("worlds.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    persona: Mapped[dict] = mapped_column(JSONB, default=dict)
    speaking_style: Mapped[dict] = mapped_column(JSONB, default=dict)
    relationship_to_user: Mapped[dict] = mapped_column(JSONB, default=dict)
    constraints: Mapped[dict] = mapped_column(JSONB, default=dict)

    world: Mapped[World | None] = relationship(back_populates="characters")


class Story(Base, TimestampMixin):
    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_user_updated", "user_id", text("updated_at DESC")),
        Index("ix_stories_user_world", "user_id", "world_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    world_id: Mapped[UUID | None] = mapped_column(ForeignKey("worlds.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    main_character_id: Mapped[UUID | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    current_branch_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(40), default="active")
    custom_prompt: Mapped[str | None] = mapped_column(Text)
    interaction_mode: Mapped[str] = mapped_column(String(20), default="choices", server_default="choices")
    consistency_mode: Mapped[str] = mapped_column(String(20), default="auto", server_default="auto")

    user: Mapped[User] = relationship(back_populates="stories")
    world: Mapped[World | None] = relationship(back_populates="stories")
    branches: Mapped[list["StoryBranch"]] = relationship(back_populates="story")
    messages: Mapped[list["Message"]] = relationship(back_populates="story")


class StoryBranch(Base):
    __tablename__ = "story_branches"
    __table_args__ = (
        Index("ix_story_branches_story_created", "story_id", "created_at", "id"),
        Index("ix_story_branches_parent", "parent_branch_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    parent_branch_id: Mapped[UUID | None] = mapped_column(ForeignKey("story_branches.id"))
    name: Mapped[str] = mapped_column(String(120), default="main")
    created_from_message_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="branches")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "ix_messages_story_branch_created",
            "story_id",
            "branch_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="messages")


class GenerationRequest(Base, TimestampMixin):
    __tablename__ = "generation_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_generation_requests_user_key"),
        Index("ix_generation_requests_story_branch", "story_id", "branch_id"),
        Index(
            "uq_generation_requests_processing_branch",
            "branch_id",
            unique=True,
            postgresql_where=text("status = 'processing'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("story_branches.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="processing", server_default="processing")
    expected_branch_version: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class PlotEvent(Base):
    __tablename__ = "plot_events"
    __table_args__ = (
        Index("ix_plot_events_story_branch_created", "story_id", "branch_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"), nullable=False)
    source_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    characters: Mapped[list] = mapped_column(JSONB, default=list)
    locations: Mapped[list] = mapped_column(JSONB, default=list)
    objects: Mapped[list] = mapped_column(JSONB, default=list)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoryStateSnapshot(Base):
    __tablename__ = "story_state_snapshots"
    __table_args__ = (
        Index(
            "ix_story_state_snapshots_story_branch_created",
            "story_id",
            "branch_id",
            text("created_at DESC"),
        ),
        Index("ix_story_state_snapshots_message", "message_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorySummary(Base):
    __tablename__ = "story_summaries"
    __table_args__ = (
        Index(
            "ix_story_summaries_story_branch_created",
            "story_id",
            "branch_id",
            text("created_at DESC"),
        ),
        Index("ix_story_summaries_parent_summary", "parent_summary_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"), nullable=False)
    parent_summary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("story_summaries.id", ondelete="SET NULL")
    )
    from_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    to_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    summary_type: Mapped[str] = mapped_column(String(80), default="session")
    prompt_version: Mapped[str] = mapped_column(String(80), default="session-summary-v2")
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(220))
    trigger: Mapped[str] = mapped_column(String(40), default="user_requested")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CanonFact(Base, TimestampMixin):
    __tablename__ = "canon_facts"
    __table_args__ = (
        Index(
            "ix_canon_facts_active_story_branch_rank",
            "story_id",
            "branch_id",
            text("importance DESC"),
            text("created_at DESC"),
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index("ix_canon_facts_source_message", "source_message_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"))
    character_id: Mapped[UUID | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    confidence: Mapped[float] = mapped_column(Numeric, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    superseded_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class MemoryItem(Base, TimestampMixin):
    __tablename__ = "memory_items"
    __table_args__ = (
        Index(
            "ix_memory_items_active_story_branch_rank",
            "story_id",
            "branch_id",
            text("importance DESC"),
            text("updated_at DESC"),
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index("ix_memory_items_source_message", "source_message_id"),
        Index("ix_memory_items_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    story_id: Mapped[UUID | None] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    branch_id: Mapped[UUID | None] = mapped_column(ForeignKey("story_branches.id", ondelete="CASCADE"))
    character_id: Mapped[UUID | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    memory_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    recency_score: Mapped[float] = mapped_column(Numeric, default=1.0)
    entity_tags: Mapped[list] = mapped_column(JSONB, default=list)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSONB)
    embedding_model: Mapped[str | None] = mapped_column(String(220))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_version: Mapped[str | None] = mapped_column(String(80))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "preference_type", name="uq_user_preferences_user_type"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    preference_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[int] = mapped_column(Integer, default=5)
    source: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserModelRoute(Base, TimestampMixin):
    __tablename__ = "user_model_routes"
    __table_args__ = (UniqueConstraint("user_id", "purpose", name="uq_user_model_routes_user_purpose"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(180), nullable=False)


class ModelHealthCheck(Base):
    __tablename__ = "model_health_checks"

    model: Mapped[str] = mapped_column(String(180), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        Index(
            "ix_model_calls_story_latest_llm",
            "story_id",
            text("created_at DESC"),
            postgresql_where=text("call_type = 'llm' AND status = 'succeeded'"),
        ),
        Index("ix_model_calls_created", "created_at"),
        Index("ix_model_calls_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    story_id: Mapped[UUID | None] = mapped_column(ForeignKey("stories.id", ondelete="SET NULL"))
    turn_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    call_type: Mapped[str] = mapped_column(String(20), default="llm", server_default="llm")
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(180), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(20), default="succeeded", server_default="succeeded")
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    first_token_latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage_estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    pricing_version: Mapped[str | None] = mapped_column(String(80))
    cost_estimate: Mapped[float | None] = mapped_column(Numeric)
    request: Mapped[dict] = mapped_column(JSONB, default=dict)
    response: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaResetEvent(Base):
    __tablename__ = "quota_reset_events"
    __table_args__ = (Index("ix_quota_reset_events_effective", text("effective_at DESC")),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    reset_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(220), default="Manual administrator reset")
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
