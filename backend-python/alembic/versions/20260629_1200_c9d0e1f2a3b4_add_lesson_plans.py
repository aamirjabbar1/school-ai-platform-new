"""add_lesson_plans

Adds the lesson_plans table backing the AI Lesson Plan Generator. A lesson plan
is a teacher-owned, curriculum-aligned teaching schedule (weekly / monthly /
unit / annual / revision / exam-prep). The structured generated plan and the
generation inputs are stored as JSON.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'lesson_plans',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=100), nullable=False),
        sa.Column('class_name', sa.String(length=50), nullable=False),
        sa.Column('section', sa.String(length=50), nullable=True),
        sa.Column('teacher_id', sa.String(length=36), nullable=False),
        sa.Column('plan_type', sa.String(length=30), nullable=False, server_default='weekly'),
        sa.Column('board', sa.String(length=100), nullable=True),
        sa.Column('book_name', sa.String(length=255), nullable=True),
        sa.Column('academic_session', sa.String(length=40), nullable=True),
        sa.Column('start_date', sa.String(length=40), nullable=True),
        sa.Column('end_date', sa.String(length=40), nullable=True),
        sa.Column('plan_data', sa.JSON(), nullable=False),
        sa.Column('inputs', sa.JSON(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lesson_plans_teacher_id', 'lesson_plans', ['teacher_id'])


def downgrade() -> None:
    op.drop_index('ix_lesson_plans_teacher_id', table_name='lesson_plans')
    op.drop_table('lesson_plans')
