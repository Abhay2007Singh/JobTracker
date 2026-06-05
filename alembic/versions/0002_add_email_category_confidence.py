"""Add email_category and confidence columns to applications.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # email_category stores the EmailCategory value from the classifier
    # (APPLICATION_CONFIRMATION, INTERVIEW_INVITATION, JOB_OFFER, REJECTION, STATUS_UPDATE)
    op.add_column("applications", sa.Column("email_category", sa.String(50), nullable=True))
    # confidence stores the Gemini AI confidence score (0.0 – 1.0)
    op.add_column("applications", sa.Column("confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "confidence")
    op.drop_column("applications", "email_category")
