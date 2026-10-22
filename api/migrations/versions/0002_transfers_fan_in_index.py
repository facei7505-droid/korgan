"""Composite index for the recipient fan-in check.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transfers") as batch_op:
        batch_op.create_index("ix_transfers_recipient_hash_created_at", ["recipient_hash", "created_at"])
        batch_op.drop_index("ix_transfers_recipient_hash")


def downgrade() -> None:
    with op.batch_alter_table("transfers") as batch_op:
        batch_op.create_index("ix_transfers_recipient_hash", ["recipient_hash"])
        batch_op.drop_index("ix_transfers_recipient_hash_created_at")
