"""add_erp_voucher_print

Voucher printing — the challan number the bank scans, the KuickPay id, the
valid-till date and the child number, plus a settings row for everything on the
printed voucher that is school policy rather than layout.

Drawn from the voucher LSS already issues. Parents recognise their voucher and
a teller recognises the layout they stamp forty times a morning; changing either
is a cost with no benefit.

Additive: no pre-existing table is altered, and `users` is referenced by foreign
key only. The module ships behind a flag that defaults off.

Revision ID: 5c8462bacd1f
Revises: d93f0665af77
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5c8462bacd1f'
down_revision: Union[str, None] = 'd93f0665af77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('voucher_settings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('school_name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('website', sa.String(length=120), nullable=True),
    sa.Column('bank_name', sa.String(length=80), nullable=True),
    sa.Column('bank_account', sa.String(length=60), nullable=True),
    sa.Column('campus_code', sa.String(length=30), nullable=True),
    sa.Column('post_to', sa.String(length=60), nullable=True),
    sa.Column('bank_line', sa.String(length=200), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('late_fine_per_day', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('valid_days_after_due', sa.Integer(), nullable=False),
    sa.Column('challan_pattern', sa.String(length=60), nullable=True),
    sa.Column('kuickpay_prefix', sa.String(length=20), nullable=True),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('vouchers', sa.Column('challan_no', sa.String(length=30), nullable=True))
    op.add_column('vouchers', sa.Column('kuickpay_id', sa.String(length=30), nullable=True))
    op.add_column('vouchers', sa.Column('valid_till', sa.Date(), nullable=True))
    op.add_column('vouchers', sa.Column('child_number', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_vouchers_challan_no'), 'vouchers', ['challan_no'], unique=False)
    op.create_index(op.f('ix_vouchers_kuickpay_id'), 'vouchers', ['kuickpay_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vouchers_kuickpay_id'), table_name='vouchers')
    op.drop_index(op.f('ix_vouchers_challan_no'), table_name='vouchers')
    op.drop_column('vouchers', 'child_number')
    op.drop_column('vouchers', 'valid_till')
    op.drop_column('vouchers', 'kuickpay_id')
    op.drop_column('vouchers', 'challan_no')
    op.drop_table('voucher_settings')
