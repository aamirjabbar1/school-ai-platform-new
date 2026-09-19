"""add_erp_foundations

ERP phase 1 — the masters, identity, access-control, audit and event tables the
rest of the programme is built on (docs/ERP_BLUEPRINT.md, Part 1).

Purely additive. No existing table is altered, no column is renamed or dropped,
and every reference to `users` is a foreign key only — so the live platform
(755 students, 45 staff, online classes, lesson plans, question papers) is
untouched, and this migration is safe to roll back.

Autogenerate also proposed dropping four indexes on `content_revisions`,
`lesson_plans` and `question_papers`. They were created by earlier migrations
and are simply not declared in the model metadata; dropping them would quietly
slow down live queries, so they are deliberately left alone.

The ERP ships switched off: `feature_flags.erp` defaults to false, so deploying
this changes nothing anyone can see until an Owner turns it on.

Revision ID: d58c75ac40b7
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd58c75ac40b7'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('academic_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('domain_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('processed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    op.create_index(op.f('ix_domain_events_event_type'), 'domain_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_domain_events_status'), 'domain_events', ['status'], unique=False)
    op.create_table('families',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('family_code', sa.String(length=30), nullable=False),
    sa.Column('father_name', sa.String(length=150), nullable=True),
    sa.Column('mother_name', sa.String(length=150), nullable=True),
    sa.Column('guardian_name', sa.String(length=150), nullable=True),
    sa.Column('guardian_relation', sa.String(length=40), nullable=True),
    sa.Column('cnic', sa.String(length=20), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('alt_phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=150), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('family_code')
    )
    op.create_index(op.f('ix_families_cnic'), 'families', ['cnic'], unique=False)
    op.create_index(op.f('ix_families_father_name'), 'families', ['father_name'], unique=False)
    op.create_index(op.f('ix_families_phone'), 'families', ['phone'], unique=False)
    op.create_table('number_series',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('scope', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=True),
    sa.Column('pattern', sa.String(length=80), nullable=False),
    sa.Column('next_value', sa.Integer(), nullable=False),
    sa.Column('reset_policy', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope')
    )
    op.create_table('roles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('school_classes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('canonical_name', sa.String(length=50), nullable=False),
    sa.Column('level', sa.String(length=20), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canonical_name')
    )
    op.create_table('subjects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('short_name', sa.String(length=20), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('actor_user_id', sa.String(length=36), nullable=True),
    sa.Column('actor_name', sa.String(length=100), nullable=True),
    sa.Column('actor_role', sa.String(length=40), nullable=True),
    sa.Column('ip', sa.String(length=60), nullable=True),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('new_value', sa.JSON(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_entity', 'audit_log', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_occurred', 'audit_log', ['occurred_at'], unique=False)
    op.create_table('class_aliases',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('alias_key', sa.String(length=80), nullable=False),
    sa.Column('alias_label', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('alias_key')
    )
    op.create_index(op.f('ix_class_aliases_class_id'), 'class_aliases', ['class_id'], unique=False)
    op.create_table('class_subjects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('subject_id', sa.String(length=36), nullable=False),
    sa.Column('is_optional', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('class_id', 'subject_id', name='uq_class_subject')
    )
    op.create_index(op.f('ix_class_subjects_class_id'), 'class_subjects', ['class_id'], unique=False)
    op.create_index(op.f('ix_class_subjects_subject_id'), 'class_subjects', ['subject_id'], unique=False)
    op.create_table('employee_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('employee_no', sa.String(length=30), nullable=True),
    sa.Column('registration_no', sa.String(length=50), nullable=True),
    sa.Column('cnic', sa.String(length=20), nullable=True),
    sa.Column('father_or_husband_name', sa.String(length=150), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('photo_key', sa.String(length=300), nullable=True),
    sa.Column('emergency_contact', sa.String(length=100), nullable=True),
    sa.Column('emergency_phone', sa.String(length=30), nullable=True),
    sa.Column('designation', sa.String(length=100), nullable=True),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('joining_date', sa.Date(), nullable=True),
    sa.Column('employment_type', sa.String(length=30), nullable=True),
    sa.Column('employment_status', sa.String(length=20), nullable=False),
    sa.Column('qualification', sa.String(length=200), nullable=True),
    sa.Column('experience_years', sa.Numeric(precision=4, scale=1), nullable=True),
    sa.Column('bank_name', sa.String(length=100), nullable=True),
    sa.Column('bank_account', sa.String(length=40), nullable=True),
    sa.Column('bank_iban', sa.String(length=40), nullable=True),
    sa.Column('left_on', sa.Date(), nullable=True),
    sa.Column('leaving_reason', sa.String(length=200), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_employee_profiles_cnic'), 'employee_profiles', ['cnic'], unique=False)
    op.create_index(op.f('ix_employee_profiles_employee_no'), 'employee_profiles', ['employee_no'], unique=True)
    op.create_index(op.f('ix_employee_profiles_registration_no'), 'employee_profiles', ['registration_no'], unique=False)
    op.create_table('feature_flags',
    sa.Column('key', sa.String(length=60), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('roles', sa.JSON(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('role_permissions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('role_id', sa.String(length=36), nullable=False),
    sa.Column('permission_key', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role_id', 'permission_key', name='uq_role_permission')
    )
    op.create_index(op.f('ix_role_permissions_permission_key'), 'role_permissions', ['permission_key'], unique=False)
    op.create_index(op.f('ix_role_permissions_role_id'), 'role_permissions', ['role_id'], unique=False)
    op.create_table('sections',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=True),
    sa.Column('class_teacher_id', sa.String(length=36), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['class_teacher_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('class_id', 'name', name='uq_section_class_name')
    )
    op.create_index(op.f('ix_sections_class_id'), 'sections', ['class_id'], unique=False)
    op.create_table('student_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('gr_no', sa.String(length=30), nullable=True),
    sa.Column('admission_no', sa.String(length=30), nullable=True),
    sa.Column('registration_no', sa.String(length=50), nullable=True),
    sa.Column('family_id', sa.String(length=36), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('b_form', sa.String(length=20), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('photo_key', sa.String(length=300), nullable=True),
    sa.Column('admission_date', sa.Date(), nullable=True),
    sa.Column('previous_school', sa.String(length=200), nullable=True),
    sa.Column('previous_class', sa.String(length=50), nullable=True),
    sa.Column('emergency_contact', sa.String(length=100), nullable=True),
    sa.Column('emergency_phone', sa.String(length=30), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('left_on', sa.Date(), nullable=True),
    sa.Column('leaving_reason', sa.String(length=200), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['family_id'], ['families.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_student_profiles_admission_no'), 'student_profiles', ['admission_no'], unique=True)
    op.create_index(op.f('ix_student_profiles_family_id'), 'student_profiles', ['family_id'], unique=False)
    op.create_index(op.f('ix_student_profiles_gr_no'), 'student_profiles', ['gr_no'], unique=True)
    op.create_index(op.f('ix_student_profiles_registration_no'), 'student_profiles', ['registration_no'], unique=False)
    op.create_table('user_roles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role_id', sa.String(length=36), nullable=False),
    sa.Column('granted_by', sa.String(length=36), nullable=True),
    sa.Column('granted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role')
    )
    op.create_index(op.f('ix_user_roles_role_id'), 'user_roles', ['role_id'], unique=False)
    op.create_index(op.f('ix_user_roles_user_id'), 'user_roles', ['user_id'], unique=False)
    op.create_table('enrollments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('student_user_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('roll_no', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('enrolled_on', sa.Date(), nullable=True),
    sa.Column('left_on', sa.Date(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['student_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('student_user_id', 'session_id', name='uq_enrollment_student_session')
    )
    op.create_index('ix_enrollment_session_class_section', 'enrollments', ['session_id', 'class_id', 'section_id'], unique=False)
    op.create_index(op.f('ix_enrollments_class_id'), 'enrollments', ['class_id'], unique=False)
    op.create_index(op.f('ix_enrollments_section_id'), 'enrollments', ['section_id'], unique=False)
    op.create_index(op.f('ix_enrollments_session_id'), 'enrollments', ['session_id'], unique=False)
    op.create_index(op.f('ix_enrollments_student_user_id'), 'enrollments', ['student_user_id'], unique=False)
    op.create_table('teacher_assignments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('teacher_user_id', sa.String(length=36), nullable=False),
    sa.Column('class_id', sa.String(length=36), nullable=False),
    sa.Column('section_id', sa.String(length=36), nullable=True),
    sa.Column('subject_id', sa.String(length=36), nullable=True),
    sa.Column('is_class_teacher', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['class_id'], ['school_classes.id'], ),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
    sa.ForeignKeyConstraint(['teacher_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'teacher_user_id', 'class_id', 'section_id', 'subject_id', name='uq_teacher_assignment')
    )
    op.create_index(op.f('ix_teacher_assignments_class_id'), 'teacher_assignments', ['class_id'], unique=False)
    op.create_index(op.f('ix_teacher_assignments_session_id'), 'teacher_assignments', ['session_id'], unique=False)
    op.create_index(op.f('ix_teacher_assignments_teacher_user_id'), 'teacher_assignments', ['teacher_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_teacher_assignments_teacher_user_id'), table_name='teacher_assignments')
    op.drop_index(op.f('ix_teacher_assignments_session_id'), table_name='teacher_assignments')
    op.drop_index(op.f('ix_teacher_assignments_class_id'), table_name='teacher_assignments')
    op.drop_table('teacher_assignments')
    op.drop_index(op.f('ix_enrollments_student_user_id'), table_name='enrollments')
    op.drop_index(op.f('ix_enrollments_session_id'), table_name='enrollments')
    op.drop_index(op.f('ix_enrollments_section_id'), table_name='enrollments')
    op.drop_index(op.f('ix_enrollments_class_id'), table_name='enrollments')
    op.drop_index('ix_enrollment_session_class_section', table_name='enrollments')
    op.drop_table('enrollments')
    op.drop_index(op.f('ix_user_roles_user_id'), table_name='user_roles')
    op.drop_index(op.f('ix_user_roles_role_id'), table_name='user_roles')
    op.drop_table('user_roles')
    op.drop_index(op.f('ix_student_profiles_registration_no'), table_name='student_profiles')
    op.drop_index(op.f('ix_student_profiles_gr_no'), table_name='student_profiles')
    op.drop_index(op.f('ix_student_profiles_family_id'), table_name='student_profiles')
    op.drop_index(op.f('ix_student_profiles_admission_no'), table_name='student_profiles')
    op.drop_table('student_profiles')
    op.drop_index(op.f('ix_sections_class_id'), table_name='sections')
    op.drop_table('sections')
    op.drop_index(op.f('ix_role_permissions_role_id'), table_name='role_permissions')
    op.drop_index(op.f('ix_role_permissions_permission_key'), table_name='role_permissions')
    op.drop_table('role_permissions')
    op.drop_table('feature_flags')
    op.drop_index(op.f('ix_employee_profiles_registration_no'), table_name='employee_profiles')
    op.drop_index(op.f('ix_employee_profiles_employee_no'), table_name='employee_profiles')
    op.drop_index(op.f('ix_employee_profiles_cnic'), table_name='employee_profiles')
    op.drop_table('employee_profiles')
    op.drop_index(op.f('ix_class_subjects_subject_id'), table_name='class_subjects')
    op.drop_index(op.f('ix_class_subjects_class_id'), table_name='class_subjects')
    op.drop_table('class_subjects')
    op.drop_index(op.f('ix_class_aliases_class_id'), table_name='class_aliases')
    op.drop_table('class_aliases')
    op.drop_index('ix_audit_occurred', table_name='audit_log')
    op.drop_index('ix_audit_entity', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('subjects')
    op.drop_table('school_classes')
    op.drop_table('roles')
    op.drop_table('number_series')
    op.drop_index(op.f('ix_families_phone'), table_name='families')
    op.drop_index(op.f('ix_families_father_name'), table_name='families')
    op.drop_index(op.f('ix_families_cnic'), table_name='families')
    op.drop_table('families')
    op.drop_index(op.f('ix_domain_events_status'), table_name='domain_events')
    op.drop_index(op.f('ix_domain_events_event_type'), table_name='domain_events')
    op.drop_table('domain_events')
    op.drop_table('academic_sessions')
