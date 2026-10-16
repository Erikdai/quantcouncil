"""Persist extracted hypotheses, immutable contracts and evidence reviews."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "thesis_extractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_job_id",
            sa.String(36),
            sa.ForeignKey("research_jobs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("candidates", JSONB(), nullable=False),
        sa.Column("outputs", JSONB(), nullable=False),
        sa.Column("model", JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        *timestamps(),
    )
    op.create_table(
        "theses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False, index=True),
        sa.Column("lifecycle", sa.String(24), nullable=False, index=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("judgment", sa.String(24)),
        sa.Column("data_health", sa.String(24), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_review_id", sa.String(36)),
        *timestamps(),
    )
    op.create_table(
        "thesis_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "thesis_id", sa.String(36), sa.ForeignKey("theses.id"), nullable=False, index=True
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("rule", JSONB()),
        sa.Column("origin", JSONB(), nullable=False),
        sa.Column("contract_hash", sa.String(64), nullable=False),
        sa.Column("model", JSONB(), nullable=False),
        sa.Column("meaning_review", JSONB()),
        sa.Column("baseline_review_id", sa.String(36)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmation", JSONB()),
        sa.UniqueConstraint("thesis_id", "number"),
        *timestamps(),
    )
    op.create_table(
        "thesis_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "thesis_id", sa.String(36), sa.ForeignKey("theses.id"), nullable=False, index=True
        ),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("thesis_versions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("evidence_key", sa.String(64)),
        sa.Column("snapshot", JSONB()),
        sa.Column("result", JSONB()),
        sa.Column("outputs", JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("version_id", "evidence_key"),
        *timestamps(),
    )
    # A process crash or concurrent manual/scheduled requests cannot create two live checks.
    op.create_index(
        "uq_thesis_live_review",
        "thesis_reviews",
        ["thesis_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade():
    for table in ["thesis_reviews", "thesis_versions", "theses", "thesis_extractions"]:
        op.drop_table(table)
