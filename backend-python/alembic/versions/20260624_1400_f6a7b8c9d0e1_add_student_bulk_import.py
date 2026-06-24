"""add_student_bulk_import

Adds everything for the bulk student import feature, including section support:
  * users.father_name        — father's name (collected during bulk import)
  * users.section            — a student's section within their class (e.g. "A")
  * users.assigned_sections  — class+section combos assigned to a teacher (JSON,
                               e.g. "Grade 5 - A")
  * student_import_batches    — tracks each bulk Excel import: live status,
    summary counts, error log, created account ids (for rollback), and
    section_mode (create | strict) for handling unknown sections.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-24 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('father_name', sa.String(length=150), nullable=True))
    op.add_column('users', sa.Column('section', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('assigned_sections', sa.JSON(), nullable=True))

    op.create_table(
        'student_import_batches',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('duplicate_mode', sa.String(length=20), nullable=False, server_default='skip'),
        sa.Column('password_mode', sa.String(length=20), nullable=False, server_default='registration'),
        sa.Column('section_mode', sa.String(length=20), nullable=False, server_default='create'),
        sa.Column('total', sa.Integer(), nullable=True),
        sa.Column('created_count', sa.Integer(), nullable=True),
        sa.Column('updated_count', sa.Integer(), nullable=True),
        sa.Column('skipped_count', sa.Integer(), nullable=True),
        sa.Column('failed_count', sa.Integer(), nullable=True),
        sa.Column('error_log', sa.JSON(), nullable=True),
        sa.Column('created_user_ids', sa.JSON(), nullable=True),
        sa.Column('has_credentials', sa.Boolean(), nullable=True),
        sa.Column('is_rolled_back', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('student_import_batches')
    op.drop_column('users', 'assigned_sections')
    op.drop_column('users', 'section')
    op.drop_column('users', 'father_name')
