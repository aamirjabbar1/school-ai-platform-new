"""add_curriculum_mappings

Adds the curriculum_mappings table that maps a student's enrolled class
(source_class) to the knowledge-base class whose content should be searched
(target_class). Supports the Pre-Board structure where e.g. Grade 8 students
study the Grade 9 curriculum.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'curriculum_mappings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('source_class', sa.String(length=50), nullable=False),
        sa.Column('target_class', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_class'),
    )


def downgrade() -> None:
    op.drop_table('curriculum_mappings')
