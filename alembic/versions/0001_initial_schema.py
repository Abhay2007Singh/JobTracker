"""Initial schema — creates the applications table.

Revision ID: 0001
Revises:
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id",                       sa.Integer(),      autoincrement=True, nullable=False),
        sa.Column("email_id",                 sa.String(255),    nullable=False),
        sa.Column("email_subject",            sa.String(500),    nullable=False),
        sa.Column("email_date",               sa.DateTime(),     nullable=False),
        sa.Column("email_sender",             sa.String(255),    nullable=False),
        sa.Column("company",                  sa.String(255),    nullable=False),
        sa.Column("role",                     sa.String(255),    nullable=False),
        sa.Column("platform",                 sa.String(50),     nullable=False),
        sa.Column("job_url",                  sa.String(1000),   nullable=True),
        sa.Column("job_description_snippet",  sa.Text(),         nullable=True),
        sa.Column("location",                 sa.String(255),    nullable=True),
        sa.Column("salary_range",             sa.String(100),    nullable=True),
        sa.Column("status",                   sa.String(50),     nullable=False),
        sa.Column("followup_days",            sa.Integer(),      nullable=True),
        sa.Column("followup_date",            sa.Date(),         nullable=True),
        sa.Column("followup_sent",            sa.Boolean(),      nullable=False),
        sa.Column("is_duplicate",             sa.Boolean(),      nullable=False),
        sa.Column("duplicate_of_id",          sa.Integer(),      nullable=True),
        sa.Column("sheets_row_index",         sa.Integer(),      nullable=True),
        sa.Column("notes",                    sa.Text(),         nullable=True),
        sa.Column("created_at",               sa.DateTime(),     nullable=False),
        sa.Column("updated_at",               sa.DateTime(),     nullable=False),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_email_id", "applications", ["email_id"], unique=True)
    op.create_index("ix_applications_status",   "applications", ["status"],   unique=False)


def downgrade() -> None:
    op.drop_index("ix_applications_status",   table_name="applications")
    op.drop_index("ix_applications_email_id", table_name="applications")
    op.drop_table("applications")
