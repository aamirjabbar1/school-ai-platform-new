"""add_erp_accounting

ERP phase 6 — double-entry accounting: chart of accounts, journals, lines,
periods, vendors, expenses and imported bank lines.

A journal carries its own totals with a CHECK that they are equal, so an
unbalanced entry cannot exist in the database whatever the application believes.
dedupe_key is unique, so an event replayed by the outbox posts exactly once —
which is the only reason retrying the outbox is safe.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: 6794e7816881
Revises: 29ea4c9fa821
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6794e7816881'
down_revision: Union[str, None] = '29ea4c9fa821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('gl_accounts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('account_type', sa.String(length=20), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('is_postable', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['gl_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_gl_accounts_code'), 'gl_accounts', ['code'], unique=True)
    op.create_table('vendors',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('contact_person', sa.String(length=120), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=150), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('tax_number', sa.String(length=40), nullable=True),
    sa.Column('bank_name', sa.String(length=100), nullable=True),
    sa.Column('bank_account', sa.String(length=40), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('accounting_periods',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('locked_by', sa.String(length=36), nullable=True),
    sa.Column('locked_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['locked_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('period')
    )
    op.create_table('journals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('journal_no', sa.String(length=30), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=True),
    sa.Column('source_id', sa.String(length=36), nullable=True),
    sa.Column('dedupe_key', sa.String(length=120), nullable=True),
    sa.Column('memo', sa.String(length=300), nullable=True),
    sa.Column('total_debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reversal_of', sa.String(length=36), nullable=True),
    sa.Column('reversal_reason', sa.String(length=200), nullable=True),
    sa.Column('posted_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('total_debit = total_credit', name='ck_journal_balanced'),
    sa.ForeignKeyConstraint(['posted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reversal_of'], ['journals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key', name='uq_journal_dedupe')
    )
    op.create_index('ix_journal_date', 'journals', ['entry_date'], unique=False)
    op.create_index('ix_journal_period', 'journals', ['period'], unique=False)
    op.create_index('ix_journal_source', 'journals', ['source_type', 'source_id'], unique=False)
    op.create_index(op.f('ix_journals_journal_no'), 'journals', ['journal_no'], unique=True)
    op.create_table('expenses',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('expense_no', sa.String(length=30), nullable=False),
    sa.Column('expense_date', sa.Date(), nullable=False),
    sa.Column('account_id', sa.String(length=36), nullable=False),
    sa.Column('vendor_id', sa.String(length=36), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('paid_from', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=80), nullable=True),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('journal_id', sa.String(length=36), nullable=True),
    sa.Column('recorded_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['gl_accounts.id'], ),
    sa.ForeignKeyConstraint(['journal_id'], ['journals.id'], ),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_expense_date', 'expenses', ['expense_date'], unique=False)
    op.create_index(op.f('ix_expenses_expense_no'), 'expenses', ['expense_no'], unique=True)
    op.create_table('journal_lines',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('journal_id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.String(length=36), nullable=False),
    sa.Column('debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('memo', sa.String(length=200), nullable=True),
    sa.CheckConstraint('NOT (debit > 0 AND credit > 0)', name='ck_line_one_side'),
    sa.CheckConstraint('debit >= 0 AND credit >= 0', name='ck_line_non_negative'),
    sa.ForeignKeyConstraint(['account_id'], ['gl_accounts.id'], ),
    sa.ForeignKeyConstraint(['journal_id'], ['journals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_journal_line_account', 'journal_lines', ['account_id'], unique=False)
    op.create_index(op.f('ix_journal_lines_journal_id'), 'journal_lines', ['journal_id'], unique=False)
    op.create_table('bank_statement_lines',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.String(length=36), nullable=True),
    sa.Column('value_date', sa.Date(), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('reference', sa.String(length=80), nullable=True),
    sa.Column('debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('import_key', sa.String(length=160), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('matched_journal_id', sa.String(length=36), nullable=True),
    sa.Column('matched_receipt_id', sa.String(length=36), nullable=True),
    sa.Column('matched_by', sa.String(length=36), nullable=True),
    sa.Column('matched_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['gl_accounts.id'], ),
    sa.ForeignKeyConstraint(['matched_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['matched_journal_id'], ['journals.id'], ),
    sa.ForeignKeyConstraint(['matched_receipt_id'], ['receipts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('import_key', name='uq_bank_line_import')
    )
    op.create_index('ix_bank_line_date', 'bank_statement_lines', ['value_date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_bank_line_date', table_name='bank_statement_lines')
    op.drop_table('bank_statement_lines')
    op.drop_index(op.f('ix_journal_lines_journal_id'), table_name='journal_lines')
    op.drop_index('ix_journal_line_account', table_name='journal_lines')
    op.drop_table('journal_lines')
    op.drop_index(op.f('ix_expenses_expense_no'), table_name='expenses')
    op.drop_index('ix_expense_date', table_name='expenses')
    op.drop_table('expenses')
    op.drop_index(op.f('ix_journals_journal_no'), table_name='journals')
    op.drop_index('ix_journal_source', table_name='journals')
    op.drop_index('ix_journal_period', table_name='journals')
    op.drop_index('ix_journal_date', table_name='journals')
    op.drop_table('journals')
    op.drop_table('accounting_periods')
    op.drop_table('vendors')
    op.drop_index(op.f('ix_gl_accounts_code'), table_name='gl_accounts')
    op.drop_table('gl_accounts')
