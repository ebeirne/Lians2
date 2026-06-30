"""api_keys.barrier_group for SSO->barrier mapping

Revision ID: 0017_apikey_barrier
Revises: 0016_pending_admissions
Create Date: 2026-06-30

When set, every read/write under the key is scoped to this information barrier.
An SSO gateway picks the key from the caller's IdP group, so the
group -> namespace/role/barrier chain is enforced end to end.
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_apikey_barrier"
down_revision = "0016_pending_admissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("barrier_group", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "barrier_group")
