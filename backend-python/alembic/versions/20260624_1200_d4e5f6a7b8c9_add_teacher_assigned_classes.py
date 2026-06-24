"""add_teacher_assigned_classes

Adds assigned_classes JSON column to users table.
Holds the list of class names assigned to a teacher (unused for other roles).
Nullable with no server default — existing rows stay NULL and are coerced to []
in User.to_dict(), matching the existing `subjects` column behaviour.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('assigned_classes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'assigned_classes')
