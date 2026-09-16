"""add_online_classes

Creates the Online Classes module schema (see docs/ONLINE_CLASSES_ARCHITECTURE.md).

Purely additive: no existing table is altered. `users`, `documents` and
`lesson_plans` are referenced by foreign key only, so the rest of LSS Bot is
untouched and this migration is safe to roll back.

Tables for recording and the AI layer are created now even though those
features land in later phases — so switching them on never requires a
migration against a live database.

Revision ID: a1b2c3d4e5f6
Revises: e1f2a3b4c5d6
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── Schedules ────────────────────────────────────────────────────────────
    op.create_table(
        'online_class_schedules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('teacher_id', sa.String(length=36), nullable=False),
        sa.Column('subject', sa.String(length=100), nullable=False),
        sa.Column('class_name', sa.String(length=50), nullable=False),
        sa.Column('section', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('recurrence', sa.String(length=20), nullable=False, server_default='weekly'),
        sa.Column('weekday', sa.Integer(), nullable=True),
        sa.Column('class_date', sa.Date(), nullable=True),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='40'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('recording_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_schedules_teacher_id', 'online_class_schedules', ['teacher_id'])

    # ─── Sessions ─────────────────────────────────────────────────────────────
    op.create_table(
        'online_class_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('schedule_id', sa.String(length=36), nullable=True),
        sa.Column('teacher_id', sa.String(length=36), nullable=False),
        sa.Column('teacher_name', sa.String(length=100), nullable=True),
        sa.Column('subject', sa.String(length=100), nullable=False),
        sa.Column('class_name', sa.String(length=50), nullable=False),
        sa.Column('section', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='scheduled'),
        sa.Column('room_name', sa.String(length=80), nullable=False),
        sa.Column('scheduled_start', sa.DateTime(), nullable=True),
        sa.Column('actual_start', sa.DateTime(), nullable=True),
        sa.Column('actual_end', sa.DateTime(), nullable=True),
        sa.Column('planned_duration_minutes', sa.Integer(), nullable=False, server_default='40'),
        sa.Column('stage_mode', sa.String(length=20), nullable=False, server_default='camera'),
        sa.Column('stage_state', sa.JSON(), nullable=True),
        sa.Column('young_mode', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('mic_locked', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('cameras_locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('low_bandwidth_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recording_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recording_status', sa.String(length=20), nullable=False, server_default='off'),
        sa.Column('lesson_plan_id', sa.String(length=36), nullable=True),
        sa.Column('lesson_plan_ref', sa.String(length=120), nullable=True),
        sa.Column('teacher_disconnected_at', sa.DateTime(), nullable=True),
        sa.Column('end_reason', sa.String(length=40), nullable=True),
        sa.Column('academic_session', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_id'], ['online_class_schedules.id']),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.ForeignKeyConstraint(['lesson_plan_id'], ['lesson_plans.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('room_name'),
    )
    op.create_index('ix_online_class_sessions_teacher_id', 'online_class_sessions', ['teacher_id'])
    op.create_index('ix_online_class_sessions_status', 'online_class_sessions', ['status'])
    op.create_index('ix_ocs_class_section_status', 'online_class_sessions',
                    ['class_name', 'section', 'status'])
    op.create_index('ix_ocs_teacher_status', 'online_class_sessions', ['teacher_id', 'status'])

    # ─── Attendance ───────────────────────────────────────────────────────────
    op.create_table(
        'online_class_participants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='student'),
        sa.Column('user_name', sa.String(length=100), nullable=True),
        sa.Column('class_name', sa.String(length=50), nullable=True),
        sa.Column('section', sa.String(length=50), nullable=True),
        sa.Column('first_join_at', sa.DateTime(), nullable=True),
        sa.Column('last_join_at', sa.DateTime(), nullable=True),
        sa.Column('last_leave_at', sa.DateTime(), nullable=True),
        sa.Column('total_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejoin_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_connected', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('attendance_percent', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='absent'),
        sa.Column('finalized', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_participants_session_id', 'online_class_participants', ['session_id'])
    op.create_index('ix_online_class_participants_user_id', 'online_class_participants', ['user_id'])
    op.create_index('ix_ocp_session_user', 'online_class_participants',
                    ['session_id', 'user_id'], unique=True)

    op.create_table(
        'online_class_attendance_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('event', sa.String(length=20), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('participant_sid', sa.String(length=80), nullable=True),
        sa.Column('reason', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_attendance_events_session_id',
                    'online_class_attendance_events', ['session_id'])
    op.create_index('ix_online_class_attendance_events_user_id',
                    'online_class_attendance_events', ['user_id'])

    # ─── Structured classroom events ──────────────────────────────────────────
    op.create_table(
        'online_class_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=True),
        sa.Column('actor_role', sa.String(length=20), nullable=True),
        sa.Column('type', sa.String(length=40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_events_session_id', 'online_class_events', ['session_id'])
    op.create_index('ix_online_class_events_type', 'online_class_events', ['type'])

    op.create_table(
        'online_class_resources',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('resource_type', sa.String(length=40), nullable=True),
        sa.Column('pages_presented', sa.JSON(), nullable=True),
        sa.Column('first_shown_at', sa.DateTime(), nullable=True),
        sa.Column('last_shown_at', sa.DateTime(), nullable=True),
        sa.Column('total_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_resources_session_id', 'online_class_resources', ['session_id'])

    op.create_table(
        'online_class_whiteboards',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('strokes', sa.JSON(), nullable=True),
        sa.Column('image_object', sa.String(length=500), nullable=True),
        sa.Column('saved_by', sa.String(length=36), nullable=True),
        sa.Column('include_in_lesson_record', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['saved_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_whiteboards_session_id', 'online_class_whiteboards', ['session_id'])

    op.create_table(
        'online_class_lesson_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('lesson_plan_id', sa.String(length=36), nullable=True),
        sa.Column('topics_covered', sa.JSON(), nullable=True),
        sa.Column('pages_covered', sa.JSON(), nullable=True),
        sa.Column('homework', sa.Text(), nullable=True),
        sa.Column('teacher_notes', sa.Text(), nullable=True),
        sa.Column('ai_suggestion', sa.JSON(), nullable=True),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('confirmed_by', sa.String(length=36), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lesson_plan_id'], ['lesson_plans.id']),
        sa.ForeignKeyConstraint(['confirmed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )

    # ─── Recording (Phase 3) ──────────────────────────────────────────────────
    op.create_table(
        'online_class_recordings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('egress_id', sa.String(length=80), nullable=True),
        sa.Column('bucket', sa.String(length=100), nullable=True),
        sa.Column('object_name', sa.String(length=500), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='starting'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('retention_days', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_recordings_session_id', 'online_class_recordings', ['session_id'])
    op.create_index('ix_online_class_recordings_expires_at', 'online_class_recordings', ['expires_at'])

    # ─── AI enhancement layer (Phase 4) ───────────────────────────────────────
    op.create_table(
        'online_class_ai_outputs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('content', sa.JSON(), nullable=True),
        sa.Column('sources', sa.JSON(), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('is_stale', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_ai_outputs_session_id', 'online_class_ai_outputs', ['session_id'])
    op.create_index('ix_ocaio_session_kind', 'online_class_ai_outputs',
                    ['session_id', 'kind'], unique=True)

    op.create_table(
        'online_class_ai_questions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column('sources', sa.JSON(), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='answered'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_online_class_ai_questions_session_id', 'online_class_ai_questions', ['session_id'])
    op.create_index('ix_online_class_ai_questions_student_id', 'online_class_ai_questions', ['student_id'])

    op.create_table(
        'ai_usage_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('feature', sa.String(length=40), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('user_role', sa.String(length=20), nullable=True),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('class_name', sa.String(length=50), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('est_cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='ok'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['online_class_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_usage_events_feature', 'ai_usage_events', ['feature'])
    op.create_index('ix_ai_usage_events_user_id', 'ai_usage_events', ['user_id'])
    op.create_index('ix_ai_usage_events_session_id', 'ai_usage_events', ['session_id'])
    op.create_index('ix_ai_usage_events_created_at', 'ai_usage_events', ['created_at'])

    # ─── Settings (single row, seeded with defaults) ──────────────────────────
    op.create_table(
        'online_class_settings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('teacher_grace_minutes', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('join_early_minutes', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('young_classes', sa.JSON(), nullable=True),
        sa.Column('present_min_percent', sa.Float(), nullable=False, server_default='75'),
        sa.Column('partial_min_percent', sa.Float(), nullable=False, server_default='25'),
        sa.Column('late_after_minutes', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('recording_enabled_globally', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recording_default_on', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recording_retention_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('max_concurrent_recordings', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('allow_admin_observe', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('announce_admin_observe', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_class_summary_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_coverage_analysis_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_revision_notes_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_ask_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_teacher_assistant_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_daily_budget_usd', sa.Float(), nullable=False, server_default='10'),
        sa.Column('ai_monthly_budget_usd', sa.Float(), nullable=False, server_default='150'),
        sa.Column('ai_max_questions_per_student_per_day', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('ai_max_calls_per_session', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('ai_model_routing', sa.JSON(), nullable=True),
        sa.Column('updated_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Seed the single settings row so the module has a configuration from the
    # first request, without needing an admin to visit a settings screen.
    op.execute(
        """
        INSERT INTO online_class_settings (id, young_classes, ai_model_routing,
                                           created_at, updated_at)
        VALUES (
            '00000000-0000-0000-0000-00000000c1a5',
            '["Pre-Nursery", "Nursery", "KG", "Class 1", "Class 2"]',
            '{}',
            NOW(), NOW()
        )
        """
    )


def downgrade() -> None:
    op.drop_table('online_class_settings')
    op.drop_table('ai_usage_events')
    op.drop_table('online_class_ai_questions')
    op.drop_table('online_class_ai_outputs')
    op.drop_table('online_class_recordings')
    op.drop_table('online_class_lesson_records')
    op.drop_table('online_class_whiteboards')
    op.drop_table('online_class_resources')
    op.drop_table('online_class_events')
    op.drop_table('online_class_attendance_events')
    op.drop_table('online_class_participants')
    op.drop_table('online_class_sessions')
    op.drop_table('online_class_schedules')
