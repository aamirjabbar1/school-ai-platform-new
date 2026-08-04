"""add_admin_review_and_revisions

Adds centralised administrative oversight of teacher-authored content:

  * review columns on lesson_plans and question_papers (approval state, who
    reviewed it and when, version counter, last editor, archive flag). These sit
    alongside is_published — review and publication are independent axes, so
    admins can review before or after a teacher publishes.
  * content_revisions: an append-only audit trail that doubles as version
    history and AI generation history for both content types.
  * question_papers.inputs / .academic_session so a paper can be regenerated and
    filtered by session the way lesson plans already can.

Existing rows default to 'pending' review at version 1.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-04 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REVIEWABLE_TABLES = ('lesson_plans', 'question_papers')


def upgrade() -> None:
    for table in _REVIEWABLE_TABLES:
        op.add_column(table, sa.Column(
            'review_status', sa.String(length=20), nullable=False, server_default='pending'))
        op.add_column(table, sa.Column('reviewed_by', sa.String(length=36), nullable=True))
        op.add_column(table, sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column('review_note', sa.Text(), nullable=True))
        op.add_column(table, sa.Column(
            'version', sa.Integer(), nullable=False, server_default='1'))
        op.add_column(table, sa.Column('updated_by', sa.String(length=36), nullable=True))
        op.add_column(table, sa.Column(
            'is_archived', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_foreign_key(
            f'fk_{table}_reviewed_by_users', table, 'users', ['reviewed_by'], ['id'])
        op.create_foreign_key(
            f'fk_{table}_updated_by_users', table, 'users', ['updated_by'], ['id'])
        op.create_index(f'ix_{table}_review_status', table, ['review_status'])

    op.add_column('question_papers', sa.Column('inputs', sa.JSON(), nullable=True))
    op.add_column('question_papers', sa.Column(
        'academic_session', sa.String(length=40), nullable=True))

    op.create_table(
        'content_revisions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('content_type', sa.String(length=30), nullable=False),
        sa.Column('content_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=True),
        sa.Column('actor_name', sa.String(length=100), nullable=True),
        sa.Column('actor_role', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('snapshot', sa.JSON(), nullable=True),
        sa.Column('ai_inputs', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_content_revisions_content_type', 'content_revisions', ['content_type'])
    op.create_index('ix_content_revisions_content_id', 'content_revisions', ['content_id'])
    op.create_index(
        'ix_content_revisions_lookup', 'content_revisions',
        ['content_type', 'content_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_content_revisions_lookup', table_name='content_revisions')
    op.drop_index('ix_content_revisions_content_id', table_name='content_revisions')
    op.drop_index('ix_content_revisions_content_type', table_name='content_revisions')
    op.drop_table('content_revisions')

    op.drop_column('question_papers', 'academic_session')
    op.drop_column('question_papers', 'inputs')

    for table in _REVIEWABLE_TABLES:
        op.drop_index(f'ix_{table}_review_status', table_name=table)
        op.drop_constraint(f'fk_{table}_updated_by_users', table, type_='foreignkey')
        op.drop_constraint(f'fk_{table}_reviewed_by_users', table, type_='foreignkey')
        op.drop_column(table, 'is_archived')
        op.drop_column(table, 'updated_by')
        op.drop_column(table, 'version')
        op.drop_column(table, 'review_note')
        op.drop_column(table, 'reviewed_at')
        op.drop_column(table, 'reviewed_by')
        op.drop_column(table, 'review_status')
