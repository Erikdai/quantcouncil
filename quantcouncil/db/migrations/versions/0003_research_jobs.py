"""Persist question-driven research, evidence and reports."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("plan", JSONB()),
        sa.Column("report", JSONB()),
        sa.Column("sources", JSONB(), nullable=False),
        sa.Column("events", JSONB(), nullable=False),
        sa.Column("model", JSONB(), nullable=False),
        sa.Column("verification", JSONB()),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("warnings", JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("research_jobs")
