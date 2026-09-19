"""add_erp_exams

ERP phase 7 — examinations, marks, grade scales, weightage schemes and report
remarks.

Marks are stored raw. Every percentage, grade and weighted total is derived at
read time by services/erp/results.py, so there is nothing stored that can drift
out of step — which is what makes the combined ledger and the combined report
card incapable of disagreeing (spec 81.F). Weightage is data, validated to total
100 before it can publish.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: d93f0665af77
Revises: 6794e7816881
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd93f0665af77'
down_revision: Union[str, None] = '6794e7816881'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('grade_scales',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('exams',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('exam_type', sa.String(length=20), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('published_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['published_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'name', name='uq_exam_session_name')
    )
    op.create_index(op.f('ix_exams_session_id'), 'exams', ['session_id'], unique=False)
    op.create_index(op.f('ix_exams_status'), 'exams', ['status'], unique=False)
    op.create_table('grade_bands',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scale_id', sa.String(length=36), nullable=False),
    sa.Column('min_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('grade', sa.String(length=10), nullable=False),
    sa.Column('grade_point', sa.Numeric(precision=4, scale=2), nullable=True),
    sa.Column('remark', sa.String(length=60), nullable=True),
    sa.ForeignKeyConstraint(['scale_id'], ['grade_scales.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_grade_bands_scale_id'), 'grade_bands', ['scale_id'], unique=False)
    op.create_table('exam_subjects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('exam_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('subject_id', sa.String(length=36), nullable=False),
    sa.Column('max_marks', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('passing_marks', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('practical_max', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('practical_passing', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('exam_date', sa.Date(), nullable=True),
    sa.Column('start_time', sa.String(length=10), nullable=True),
    sa.Column('room', sa.String(length=60), nullable=True),
    sa.Column('is_optional', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('exam_id', 'class_id', 'subject_id', name='uq_exam_subject')
    )
    op.create_index('ix_exam_subject_class', 'exam_subjects', ['exam_id', 'class_id'], unique=False)
    op.create_index(op.f('ix_exam_subjects_class_id'), 'exam_subjects', ['class_id'], unique=False)
    op.create_index(op.f('ix_exam_subjects_exam_id'), 'exam_subjects', ['exam_id'], unique=False)
    op.create_index(op.f('ix_exam_subjects_subject_id'), 'exam_subjects', ['subject_id'], unique=False)
    op.create_table('result_schemes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('grade_scale_id', sa.String(length=36), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('show_position', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['grade_scale_id'], ['grade_scales.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_result_schemes_class_id'), 'result_schemes', ['class_id'], unique=False)
    op.create_index(op.f('ix_result_schemes_session_id'), 'result_schemes', ['session_id'], unique=False)
    op.create_table('marks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('exam_subject_id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('obtained', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('practical_obtained', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('is_absent', sa.Boolean(), nullable=False),
    sa.Column('is_exempt', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('entered_by', sa.String(length=36), nullable=True),
    sa.Column('entered_at', sa.DateTime(), nullable=True),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('remark', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['exam_subject_id'], ['exam_subjects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('exam_subject_id', 'student_user_id', name='uq_mark')
    )
    op.create_index('ix_mark_student', 'marks', ['student_user_id'], unique=False)
    op.create_index(op.f('ix_marks_exam_subject_id'), 'marks', ['exam_subject_id'], unique=False)
    op.create_table('report_remarks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('scheme_id', sa.String(length=36), nullable=True),
    sa.Column('exam_id', sa.String(length=36), nullable=True),
    sa.Column('teacher_remark', sa.Text(), nullable=True),
    sa.Column('principal_remark', sa.Text(), nullable=True),
    sa.Column('promotion_status', sa.String(length=30), nullable=True),
    sa.Column('written_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ),
    sa.ForeignKeyConstraint(['scheme_id'], ['result_schemes.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['written_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_user_id', 'scheme_id', 'exam_id', name='uq_report_remark')
    )
    op.create_index(op.f('ix_report_remarks_student_user_id'), 'report_remarks', ['student_user_id'], unique=False)
    op.create_table('scheme_components',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scheme_id', sa.String(length=36), nullable=False),
    sa.Column('exam_id', sa.String(length=36), nullable=False),
    sa.Column('weight_percent', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ),
    sa.ForeignKeyConstraint(['scheme_id'], ['result_schemes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scheme_id', 'exam_id', name='uq_scheme_component')
    )
    op.create_index(op.f('ix_scheme_components_scheme_id'), 'scheme_components', ['scheme_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scheme_components_scheme_id'), table_name='scheme_components')
    op.drop_table('scheme_components')
    op.drop_index(op.f('ix_report_remarks_student_user_id'), table_name='report_remarks')
    op.drop_table('report_remarks')
    op.drop_index(op.f('ix_marks_exam_subject_id'), table_name='marks')
    op.drop_index('ix_mark_student', table_name='marks')
    op.drop_table('marks')
    op.drop_index(op.f('ix_result_schemes_session_id'), table_name='result_schemes')
    op.drop_index(op.f('ix_result_schemes_class_id'), table_name='result_schemes')
    op.drop_table('result_schemes')
    op.drop_index(op.f('ix_exam_subjects_subject_id'), table_name='exam_subjects')
    op.drop_index(op.f('ix_exam_subjects_exam_id'), table_name='exam_subjects')
    op.drop_index(op.f('ix_exam_subjects_class_id'), table_name='exam_subjects')
    op.drop_index('ix_exam_subject_class', table_name='exam_subjects')
    op.drop_table('exam_subjects')
    op.drop_index(op.f('ix_grade_bands_scale_id'), table_name='grade_bands')
    op.drop_table('grade_bands')
    op.drop_index(op.f('ix_exams_status'), table_name='exams')
    op.drop_index(op.f('ix_exams_session_id'), table_name='exams')
    op.drop_table('exams')
    op.drop_table('grade_scales')
