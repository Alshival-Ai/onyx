"""add feature_overrides to user

Revision ID: 9f6a1b2c3d4e
Revises: 631fd2504136
Create Date: 2026-02-24 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "9f6a1b2c3d4e"
down_revision = "631fd2504136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "feature_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "feature_overrides")
