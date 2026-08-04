"""add_question_paper_exam_date

Adds the date printed in the LSS question-paper header. Null means "stamp the
current date when the paper is downloaded"; teachers can pin a specific
examination date instead.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('question_papers', sa.Column('exam_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('question_papers', 'exam_date')
