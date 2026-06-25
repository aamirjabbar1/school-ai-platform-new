"""add_section_to_assignments_papers

Adds a target section to assignments and question papers so teachers can scope
them to a specific class section (e.g. "Class 5 - A"). Null = whole class
(backward compatible with existing rows).

Revision ID: b8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-06-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assignments', sa.Column('section', sa.String(length=50), nullable=True))
    op.add_column('question_papers', sa.Column('section', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('question_papers', 'section')
    op.drop_column('assignments', 'section')
