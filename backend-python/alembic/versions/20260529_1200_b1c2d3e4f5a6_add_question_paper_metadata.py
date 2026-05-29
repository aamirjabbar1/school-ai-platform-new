"""add_question_paper_metadata

Adds exam/question-paper specific metadata to the documents table:
  - paper_type: past_paper | test | midterm | final | mcqs (question papers only)
  - chapter:    chapter / topic the paper or material covers

Books leave both null. The exam Year reuses the existing academic_year column.

Revision ID: b1c2d3e4f5a6
Revises: a03a9e902522
Create Date: 2026-05-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a03a9e902522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('paper_type', sa.String(length=40), nullable=True))
    op.add_column('documents', sa.Column('chapter', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'chapter')
    op.drop_column('documents', 'paper_type')
