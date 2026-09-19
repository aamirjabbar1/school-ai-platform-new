"""add_erp_fees

ERP phase 4 — the fee engine: heads, structures, concessions, vouchers,
receipts, the student ledger and the account summary the defaulter list scans.

Every money column is NUMERIC(14,2). A float would produce statements off by a
paisa, and an office that finds one wrong total stops trusting all of them.
Receipts carry a unique bank reference, which is what makes importing the same
bank file twice harmless.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: d03fc22b0c79
Revises: 76e3f05047a3
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd03fc22b0c79'
down_revision: Union[str, None] = '76e3f05047a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('fee_heads',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('head_type', sa.String(length=20), nullable=False),
    sa.Column('is_refundable', sa.Boolean(), nullable=False),
    sa.Column('gl_code', sa.String(length=20), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('student_fee_accounts',
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('total_billed', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('outstanding', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('advance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('oldest_unpaid_month', sa.Date(), nullable=True),
    sa.Column('unpaid_months', sa.Integer(), nullable=False),
    sa.Column('last_payment_on', sa.Date(), nullable=True),
    sa.Column('last_payment_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('student_user_id')
    )
    op.create_index('ix_fee_account_outstanding', 'student_fee_accounts', ['outstanding'], unique=False)
    op.create_table('student_fee_overrides',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('head_id', sa.String(length=36), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['head_id'], ['fee_heads.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_user_id', 'session_id', 'head_id', name='uq_student_fee_override')
    )
    op.create_index(op.f('ix_student_fee_overrides_student_user_id'), 'student_fee_overrides', ['student_user_id'], unique=False)
    op.create_table('student_ledger',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('description', sa.String(length=200), nullable=False),
    sa.Column('debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('balance', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('source_type', sa.String(length=30), nullable=True),
    sa.Column('source_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ledger_student_date', 'student_ledger', ['student_user_id', 'entry_date'], unique=False)
    op.create_table('concessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=True),
    sa.Column('family_id', sa.String(length=36), nullable=True),
    sa.Column('head_id', sa.String(length=36), nullable=True),
    sa.Column('concession_type', sa.String(length=20), nullable=False),
    sa.Column('value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('document_key', sa.String(length=300), nullable=True),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], ),
    sa.ForeignKeyConstraint(['head_id'], ['fee_heads.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_concession_family', 'concessions', ['family_id'], unique=False)
    op.create_index('ix_concession_student', 'concessions', ['student_user_id'], unique=False)
    op.create_table('fee_structures',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('head_id', sa.String(length=36), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['head_id'], ['fee_heads.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'class_id', 'head_id', name='uq_fee_structure')
    )
    op.create_index(op.f('ix_fee_structures_class_id'), 'fee_structures', ['class_id'], unique=False)
    op.create_index(op.f('ix_fee_structures_head_id'), 'fee_structures', ['head_id'], unique=False)
    op.create_index(op.f('ix_fee_structures_session_id'), 'fee_structures', ['session_id'], unique=False)
    op.create_table('voucher_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=True),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_count', sa.Integer(), nullable=False),
    sa.Column('skipped_count', sa.Integer(), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('run_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['run_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('vouchers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('voucher_no', sa.String(length=30), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=True),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('issue_date', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('gross', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('concession', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('arrears', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('late_fee', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('payable', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('cancelled_reason', sa.String(length=200), nullable=True),
    sa.Column('generated_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['generated_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_user_id', 'session_id', 'month', name='uq_voucher_student_month')
    )
    op.create_index('ix_voucher_month', 'vouchers', ['month'], unique=False)
    op.create_index('ix_voucher_status', 'vouchers', ['status'], unique=False)
    op.create_index(op.f('ix_vouchers_session_id'), 'vouchers', ['session_id'], unique=False)
    op.create_index(op.f('ix_vouchers_student_user_id'), 'vouchers', ['student_user_id'], unique=False)
    op.create_index(op.f('ix_vouchers_voucher_no'), 'vouchers', ['voucher_no'], unique=True)
    op.create_table('receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('receipt_no', sa.String(length=30), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('voucher_id', sa.String(length=36), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('bank_reference', sa.String(length=80), nullable=True),
    sa.Column('received_on', sa.Date(), nullable=False),
    sa.Column('received_by', sa.String(length=36), nullable=True),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('reversal_of', sa.String(length=36), nullable=True),
    sa.Column('reversal_reason', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['received_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reversal_of'], ['receipts.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['voucher_id'], ['vouchers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bank_reference', name='uq_receipt_bank_reference')
    )
    op.create_index('ix_receipt_date', 'receipts', ['received_on'], unique=False)
    op.create_index('ix_receipt_student', 'receipts', ['student_user_id'], unique=False)
    op.create_index(op.f('ix_receipts_receipt_no'), 'receipts', ['receipt_no'], unique=True)
    op.create_index(op.f('ix_receipts_voucher_id'), 'receipts', ['voucher_id'], unique=False)
    op.create_table('voucher_lines',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('voucher_id', sa.String(length=36), nullable=False),
    sa.Column('head_id', sa.String(length=36), nullable=False),
    sa.Column('head_name', sa.String(length=100), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('concession', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('net', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['head_id'], ['fee_heads.id'], ),
    sa.ForeignKeyConstraint(['voucher_id'], ['vouchers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_voucher_lines_voucher_id'), 'voucher_lines', ['voucher_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_voucher_lines_voucher_id'), table_name='voucher_lines')
    op.drop_table('voucher_lines')
    op.drop_index(op.f('ix_receipts_voucher_id'), table_name='receipts')
    op.drop_index(op.f('ix_receipts_receipt_no'), table_name='receipts')
    op.drop_index('ix_receipt_student', table_name='receipts')
    op.drop_index('ix_receipt_date', table_name='receipts')
    op.drop_table('receipts')
    op.drop_index(op.f('ix_vouchers_voucher_no'), table_name='vouchers')
    op.drop_index(op.f('ix_vouchers_student_user_id'), table_name='vouchers')
    op.drop_index(op.f('ix_vouchers_session_id'), table_name='vouchers')
    op.drop_index('ix_voucher_status', table_name='vouchers')
    op.drop_index('ix_voucher_month', table_name='vouchers')
    op.drop_table('vouchers')
    op.drop_table('voucher_runs')
    op.drop_index(op.f('ix_fee_structures_session_id'), table_name='fee_structures')
    op.drop_index(op.f('ix_fee_structures_head_id'), table_name='fee_structures')
    op.drop_index(op.f('ix_fee_structures_class_id'), table_name='fee_structures')
    op.drop_table('fee_structures')
    op.drop_index('ix_concession_student', table_name='concessions')
    op.drop_index('ix_concession_family', table_name='concessions')
    op.drop_table('concessions')
    op.drop_index('ix_ledger_student_date', table_name='student_ledger')
    op.drop_table('student_ledger')
    op.drop_index(op.f('ix_student_fee_overrides_student_user_id'), table_name='student_fee_overrides')
    op.drop_table('student_fee_overrides')
    op.drop_index('ix_fee_account_outstanding', table_name='student_fee_accounts')
    op.drop_table('student_fee_accounts')
    op.drop_table('fee_heads')
