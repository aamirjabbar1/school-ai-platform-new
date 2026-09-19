"""add_erp_admissions_families_campus

ERP phase 2 — admissions, families, guardians, and the campus column that makes
a second campus a row rather than a migration.

Additive, like phase 1: three new tables, a nullable `campus_id` on the ERP's
own master tables, and `user_roles.scope` so a role can be held over part of the
school (the Preschool Head runs Pre-Nursery, Nursery and KG). No pre-existing
table is altered — `users` is still referenced by foreign key only.

`campus_id` is nullable and no screen shows it. LSS runs one campus, and asking
a clerk which campus a child is joining when there is only one is the sort of
question this system exists to stop asking. The column is here so that adding a
campus later does not mean a migration across every table that holds a person, a
fee or a mark.

Autogenerate again proposed dropping four indexes on `content_revisions`,
`lesson_plans` and `question_papers`; they are declared nowhere in the model
metadata but are used in production, so they are deliberately left alone. A test
in `tests/test_erp_foundations.py` fails if they ever creep back in.

Revision ID: 84718fa12791
Revises: d58c75ac40b7
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '84718fa12791'
down_revision: Union[str, None] = 'd58c75ac40b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('campuses',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=True),
    sa.Column('city', sa.String(length=80), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name')
    )
    op.create_table('guardians',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('family_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('relation', sa.String(length=40), nullable=True),
    sa.Column('cnic', sa.String(length=20), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=150), nullable=True),
    sa.Column('occupation', sa.String(length=120), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guardians_cnic'), 'guardians', ['cnic'], unique=False)
    op.create_index(op.f('ix_guardians_family_id'), 'guardians', ['family_id'], unique=False)
    op.create_index(op.f('ix_guardians_phone'), 'guardians', ['phone'], unique=False)
    op.create_table('admissions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('campus_id', sa.String(length=36), nullable=True),
    sa.Column('application_no', sa.String(length=30), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('student_name', sa.String(length=150), nullable=False),
    sa.Column('father_name', sa.String(length=150), nullable=True),
    sa.Column('mother_name', sa.String(length=150), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('b_form', sa.String(length=20), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('previous_school', sa.String(length=200), nullable=True),
    sa.Column('previous_class', sa.String(length=50), nullable=True),
    sa.Column('session_id', sa.String(length=36), nullable=True),
    sa.Column('class_applied_id', sa.String(length=36), nullable=True),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('family_id', sa.String(length=36), nullable=True),
    sa.Column('guardian_name', sa.String(length=150), nullable=True),
    sa.Column('guardian_phone', sa.String(length=30), nullable=True),
    sa.Column('emergency_contact', sa.String(length=100), nullable=True),
    sa.Column('emergency_phone', sa.String(length=30), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('inquiry_source', sa.String(length=60), nullable=True),
    sa.Column('student_user_id', sa.String(length=36), nullable=True),
    sa.Column('gr_no', sa.String(length=30), nullable=True),
    sa.Column('admission_no', sa.String(length=30), nullable=True),
    sa.Column('admission_date', sa.Date(), nullable=True),
    sa.Column('credentials_issued', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('confirmed_by', sa.String(length=36), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('rejected_reason', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['campus_id'], ['campuses.id'], ),
    sa.ForeignKeyConstraint(['class_applied_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admissions_application_no'), 'admissions', ['application_no'], unique=True)
    op.create_index(op.f('ix_admissions_campus_id'), 'admissions', ['campus_id'], unique=False)
    op.create_index(op.f('ix_admissions_class_applied_id'), 'admissions', ['class_applied_id'], unique=False)
    op.create_index(op.f('ix_admissions_family_id'), 'admissions', ['family_id'], unique=False)
    op.create_index(op.f('ix_admissions_father_name'), 'admissions', ['father_name'], unique=False)
    op.create_index(op.f('ix_admissions_phone'), 'admissions', ['phone'], unique=False)
    op.create_index(op.f('ix_admissions_session_id'), 'admissions', ['session_id'], unique=False)
    op.create_index(op.f('ix_admissions_status'), 'admissions', ['status'], unique=False)
    op.create_index(op.f('ix_admissions_student_user_id'), 'admissions', ['student_user_id'], unique=False)
    op.add_column('employee_profiles', sa.Column('campus_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_employee_profiles_campus_id'), 'employee_profiles', ['campus_id'], unique=False)
    op.create_foreign_key('fk_employee_profiles_campus_id_campuses', 'employee_profiles', 'campuses', ['campus_id'], ['id'])
    op.add_column('families', sa.Column('campus_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_families_campus_id'), 'families', ['campus_id'], unique=False)
    op.create_foreign_key('fk_families_campus_id_campuses', 'families', 'campuses', ['campus_id'], ['id'])
    op.add_column('school_classes', sa.Column('campus_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_school_classes_campus_id'), 'school_classes', ['campus_id'], unique=False)
    op.create_foreign_key('fk_school_classes_campus_id_campuses', 'school_classes', 'campuses', ['campus_id'], ['id'])
    op.add_column('sections', sa.Column('campus_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_sections_campus_id'), 'sections', ['campus_id'], unique=False)
    op.create_foreign_key('fk_sections_campus_id_campuses', 'sections', 'campuses', ['campus_id'], ['id'])
    op.add_column('student_profiles', sa.Column('campus_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_student_profiles_campus_id'), 'student_profiles', ['campus_id'], unique=False)
    op.create_foreign_key('fk_student_profiles_campus_id_campuses', 'student_profiles', 'campuses', ['campus_id'], ['id'])
    op.add_column('user_roles', sa.Column('scope', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_roles', 'scope')
    op.drop_constraint('fk_student_profiles_campus_id_campuses', 'student_profiles', type_='foreignkey')
    op.drop_index(op.f('ix_student_profiles_campus_id'), table_name='student_profiles')
    op.drop_column('student_profiles', 'campus_id')
    op.drop_constraint('fk_sections_campus_id_campuses', 'sections', type_='foreignkey')
    op.drop_index(op.f('ix_sections_campus_id'), table_name='sections')
    op.drop_column('sections', 'campus_id')
    op.drop_constraint('fk_school_classes_campus_id_campuses', 'school_classes', type_='foreignkey')
    op.drop_index(op.f('ix_school_classes_campus_id'), table_name='school_classes')
    op.drop_column('school_classes', 'campus_id')
    op.drop_constraint('fk_families_campus_id_campuses', 'families', type_='foreignkey')
    op.drop_index(op.f('ix_families_campus_id'), table_name='families')
    op.drop_column('families', 'campus_id')
    op.drop_constraint('fk_employee_profiles_campus_id_campuses', 'employee_profiles', type_='foreignkey')
    op.drop_index(op.f('ix_employee_profiles_campus_id'), table_name='employee_profiles')
    op.drop_column('employee_profiles', 'campus_id')
    op.drop_index(op.f('ix_admissions_student_user_id'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_status'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_session_id'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_phone'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_father_name'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_family_id'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_class_applied_id'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_campus_id'), table_name='admissions')
    op.drop_index(op.f('ix_admissions_application_no'), table_name='admissions')
    op.drop_table('admissions')
    op.drop_index(op.f('ix_guardians_phone'), table_name='guardians')
    op.drop_index(op.f('ix_guardians_family_id'), table_name='guardians')
    op.drop_index(op.f('ix_guardians_cnic'), table_name='guardians')
    op.drop_table('guardians')
    op.drop_table('campuses')
