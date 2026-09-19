"""add_erp_payroll

ERP phase 5 — salary structures, payroll runs and lines, employee advances
and the digital personnel file.

Salary is never overwritten: a revision closes the current structure and
inserts a new one, so increment history is free and a two-year-old payslip
still reproduces. A payroll line snapshots what it was computed from, so
approving a month freezes it.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: 29ea4c9fa821
Revises: d03fc22b0c79
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '29ea4c9fa821'
down_revision: Union[str, None] = 'd03fc22b0c79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('employee_advances',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employee_user_id', sa.String(length=36), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('instalment', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('outstanding', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('taken_on', sa.Date(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_employee_advances_employee_user_id'), 'employee_advances', ['employee_user_id'], unique=False)
    op.create_table('employee_documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employee_user_id', sa.String(length=36), nullable=False),
    sa.Column('doc_type', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('file_key', sa.String(length=300), nullable=True),
    sa.Column('issue_date', sa.Date(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['employee_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_employee_documents_employee_user_id'), 'employee_documents', ['employee_user_id'], unique=False)
    op.create_table('payroll_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('employee_count', sa.Integer(), nullable=False),
    sa.Column('total_gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_deductions', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_net', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('generated_by', sa.String(length=36), nullable=True),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('paid_on', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['generated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('month', name='uq_payroll_month')
    )
    op.create_index(op.f('ix_payroll_runs_status'), 'payroll_runs', ['status'], unique=False)
    op.create_table('salary_structures',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employee_user_id', sa.String(length=36), nullable=False),
    sa.Column('basic', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('supersedes_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id'], ['salary_structures.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_salary_employee_active', 'salary_structures', ['employee_user_id', 'is_active'], unique=False)
    op.create_index(op.f('ix_salary_structures_employee_user_id'), 'salary_structures', ['employee_user_id'], unique=False)
    op.create_table('payroll_lines',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('employee_user_id', sa.String(length=36), nullable=False),
    sa.Column('structure_id', sa.String(length=36), nullable=True),
    sa.Column('basic', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('allowances', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('deductions', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('bonus', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('arrears', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('advance_recovery', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('net', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('days_in_month', sa.Integer(), nullable=False),
    sa.Column('days_payable', sa.Integer(), nullable=False),
    sa.Column('unpaid_leave_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('is_prorated', sa.Boolean(), nullable=False),
    sa.Column('breakdown', sa.JSON(), nullable=True),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['employee_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['payroll_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structures.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'employee_user_id', name='uq_payroll_line')
    )
    op.create_index(op.f('ix_payroll_lines_employee_user_id'), 'payroll_lines', ['employee_user_id'], unique=False)
    op.create_index(op.f('ix_payroll_lines_run_id'), 'payroll_lines', ['run_id'], unique=False)
    op.create_table('salary_components',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('structure_id', sa.String(length=36), nullable=False),
    sa.Column('component_type', sa.String(length=20), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('calculation', sa.String(length=30), nullable=False),
    sa.Column('value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('is_taxable', sa.Boolean(), nullable=False),
    sa.Column('prorates', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['structure_id'], ['salary_structures.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_salary_components_structure_id'), 'salary_components', ['structure_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_salary_components_structure_id'), table_name='salary_components')
    op.drop_table('salary_components')
    op.drop_index(op.f('ix_payroll_lines_run_id'), table_name='payroll_lines')
    op.drop_index(op.f('ix_payroll_lines_employee_user_id'), table_name='payroll_lines')
    op.drop_table('payroll_lines')
    op.drop_index(op.f('ix_salary_structures_employee_user_id'), table_name='salary_structures')
    op.drop_index('ix_salary_employee_active', table_name='salary_structures')
    op.drop_table('salary_structures')
    op.drop_index(op.f('ix_payroll_runs_status'), table_name='payroll_runs')
    op.drop_table('payroll_runs')
    op.drop_index(op.f('ix_employee_documents_employee_user_id'), table_name='employee_documents')
    op.drop_table('employee_documents')
    op.drop_index(op.f('ix_employee_advances_employee_user_id'), table_name='employee_advances')
    op.drop_table('employee_advances')
