"""add_erp_attendance

ERP phase 3 — the daily register, plus the staff leave records payroll will
need to prorate an unpaid month. Attendance is recorded rather than inferred: a
class with no row is a register nobody took, which is a question for the office
and not an empty classroom.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: 76e3f05047a3
Revises: 84718fa12791
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '76e3f05047a3'
down_revision: Union[str, None] = '84718fa12791'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('leave_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employee_user_id', sa.String(length=36), nullable=False),
    sa.Column('leave_type', sa.String(length=30), nullable=False),
    sa.Column('from_date', sa.Date(), nullable=False),
    sa.Column('to_date', sa.Date(), nullable=False),
    sa.Column('days', sa.String(length=10), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('is_paid', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leave_requests_employee_user_id'), 'leave_requests', ['employee_user_id'], unique=False)
    op.create_table('attendance_days',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('marked_by', sa.String(length=36), nullable=True),
    sa.Column('marked_at', sa.DateTime(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['marked_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'class_id', 'section_id', 'date', name='uq_attendance_day')
    )
    op.create_index('ix_attendance_day_date', 'attendance_days', ['date'], unique=False)
    op.create_index(op.f('ix_attendance_days_class_id'), 'attendance_days', ['class_id'], unique=False)
    op.create_index(op.f('ix_attendance_days_section_id'), 'attendance_days', ['section_id'], unique=False)
    op.create_index(op.f('ix_attendance_days_session_id'), 'attendance_days', ['session_id'], unique=False)
    op.create_table('attendance_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('day_id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('marked_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['day_id'], ['attendance_days.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['marked_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('day_id', 'student_user_id', name='uq_attendance_record')
    )
    op.create_index(op.f('ix_attendance_records_day_id'), 'attendance_records', ['day_id'], unique=False)
    op.create_index('ix_attendance_student', 'attendance_records', ['student_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_attendance_student', table_name='attendance_records')
    op.drop_index(op.f('ix_attendance_records_day_id'), table_name='attendance_records')
    op.drop_table('attendance_records')
    op.drop_index(op.f('ix_attendance_days_session_id'), table_name='attendance_days')
    op.drop_index(op.f('ix_attendance_days_section_id'), table_name='attendance_days')
    op.drop_index(op.f('ix_attendance_days_class_id'), table_name='attendance_days')
    op.drop_index('ix_attendance_day_date', table_name='attendance_days')
    op.drop_table('attendance_days')
    op.drop_index(op.f('ix_leave_requests_employee_user_id'), table_name='leave_requests')
    op.drop_table('leave_requests')
