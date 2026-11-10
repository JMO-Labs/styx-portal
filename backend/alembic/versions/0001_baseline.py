"""baseline: schema of every model at the switch to Alembic (styx-portal#21)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('actor_ip', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('resource', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_ts'), 'audit_log', ['ts'], unique=False)
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'], unique=False)
    op.create_table('banned_ip',
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('banned_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('ip', name=op.f('pk_banned_ip'))
    )
    op.create_table('groups',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('allow_gpu', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_groups'))
    )
    op.create_index(op.f('ix_groups_name'), 'groups', ['name'], unique=True)
    op.create_table('metric_hours',
    sa.Column('ts_hour', sa.DateTime(), nullable=False),
    sa.Column('cpu_avg', sa.Float(), nullable=True),
    sa.Column('cpu_max', sa.Float(), nullable=True),
    sa.Column('ram_avg', sa.Float(), nullable=True),
    sa.Column('disk_pct', sa.Float(), nullable=False),
    sa.Column('live_max', sa.Integer(), nullable=False),
    sa.Column('health', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('ts_hour', name=op.f('pk_metric_hours'))
    )
    op.create_table('mount_jobs',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('service_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=True),
    sa.Column('changes', sa.JSON(), nullable=True),
    sa.Column('backup_dir', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('changed', sa.Boolean(), nullable=False),
    sa.Column('log_excerpt', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mount_jobs'))
    )
    op.create_index(op.f('ix_mount_jobs_service_id'), 'mount_jobs', ['service_id'], unique=False)
    op.create_table('oauth_providers',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('issuer_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('authorize_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('token_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('userinfo_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('client_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('client_secret_enc', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('scopes', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('icon_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('trust_email', sa.Boolean(), nullable=False),
    sa.Column('allow_signup', sa.Boolean(), nullable=False),
    sa.Column('auto_promote_admins', sa.Boolean(), nullable=False),
    sa.Column('role_map', sa.JSON(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_providers'))
    )
    op.create_index(op.f('ix_oauth_providers_name'), 'oauth_providers', ['name'], unique=True)
    op.create_table('proxied_services',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('upstream_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('container', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('container_port', sa.Integer(), nullable=True),
    sa.Column('upstream_fallback', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('mount_mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('auth_mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('bypass_rules', sa.JSON(), nullable=True),
    sa.Column('allowed_groups', sa.JSON(), nullable=True),
    sa.Column('verify_tls', sa.Boolean(), nullable=False),
    sa.Column('upstream_is_proxy', sa.Boolean(), nullable=False),
    sa.Column('health_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('health_status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('health_checked_at', sa.DateTime(), nullable=True),
    sa.Column('preset_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('mount_managed', sa.Boolean(), nullable=False),
    sa.Column('icon_custom', sa.Boolean(), nullable=False),
    sa.Column('pass_identity', sa.Boolean(), nullable=False),
    sa.Column('frame_ok', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proxied_services'))
    )
    op.create_index(op.f('ix_proxied_services_slug'), 'proxied_services', ['slug'], unique=True)
    op.create_table('pulled_images',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('image', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('size_mb', sa.Integer(), nullable=True),
    sa.Column('pulled_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulled_images'))
    )
    op.create_index(op.f('ix_pulled_images_image'), 'pulled_images', ['image'], unique=True)
    op.create_table('revoked_access_tokens',
    sa.Column('jti', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('jti', name=op.f('pk_revoked_access_tokens'))
    )
    op.create_table('service_presets',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('default_port', sa.Integer(), nullable=True),
    sa.Column('mount_mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('auth_mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('bypass_rules', sa.JSON(), nullable=True),
    sa.Column('health_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('verify_tls', sa.Boolean(), nullable=False),
    sa.Column('base_url_hint', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('warnings', sa.JSON(), nullable=True),
    sa.Column('subpath', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_presets'))
    )
    op.create_table('session_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('event_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_events'))
    )
    op.create_table('stream_sessions',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('target_kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('target_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('transport', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('codec', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('relayed', sa.Boolean(), nullable=False),
    sa.Column('relay_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stream_sessions'))
    )
    op.create_index(op.f('ix_stream_sessions_started_at'), 'stream_sessions', ['started_at'], unique=False)
    op.create_index(op.f('ix_stream_sessions_target_id'), 'stream_sessions', ['target_id'], unique=False)
    op.create_index(op.f('ix_stream_sessions_user_id'), 'stream_sessions', ['user_id'], unique=False)
    op.create_table('system_settings',
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_system_settings'))
    )
    op.create_table('turn_usage_day',
    sa.Column('day', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('day', name=op.f('pk_turn_usage_day'))
    )
    op.create_table('users',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('username', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('must_change_pw', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.Column('failed_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('open_workspaces', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('open_apps', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('matrix_card', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('matrix_pending', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('matrix_challenge', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('matrix_serial', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('federated_identities',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('subject', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_federated_identities_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_federated_identities')),
    sa.UniqueConstraint('provider', 'subject', name='uq_provider_subject')
    )
    op.create_index(op.f('ix_federated_identities_provider'), 'federated_identities', ['provider'], unique=False)
    op.create_index(op.f('ix_federated_identities_subject'), 'federated_identities', ['subject'], unique=False)
    op.create_index(op.f('ix_federated_identities_user_id'), 'federated_identities', ['user_id'], unique=False)
    op.create_table('invites',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_invites_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites'))
    )
    op.create_index(op.f('ix_invites_token_hash'), 'invites', ['token_hash'], unique=True)
    op.create_table('refresh_tokens',
    sa.Column('jti', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('family_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('session_only', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users')),
    sa.PrimaryKeyConstraint('jti', name=op.f('pk_refresh_tokens'))
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('service_templates',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('owner_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('image', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('env_vars', sa.JSON(), nullable=True),
    sa.Column('gpu_enabled', sa.Boolean(), nullable=False),
    sa.Column('gpu_count', sa.Integer(), nullable=False),
    sa.Column('memory_limit', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('cpu_limit', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('shm_size', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('dind', sa.Boolean(), nullable=False),
    sa.Column('cap_add', sa.JSON(), nullable=True),
    sa.Column('security_opt', sa.JSON(), nullable=True),
    sa.Column('tls_skip_verify', sa.Boolean(), nullable=False),
    sa.Column('shared', sa.Boolean(), nullable=False),
    sa.Column('restart_policy', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('read_only_rootfs', sa.Boolean(), nullable=False),
    sa.Column('tmpfs', sa.JSON(), nullable=True),
    sa.Column('extra_hosts', sa.JSON(), nullable=True),
    sa.Column('ulimits', sa.JSON(), nullable=True),
    sa.Column('extra_ports', sa.JSON(), nullable=True),
    sa.Column('entrypoint', sa.JSON(), nullable=True),
    sa.Column('command', sa.JSON(), nullable=True),
    sa.Column('devices', sa.JSON(), nullable=True),
    sa.Column('privileged', sa.Boolean(), nullable=False),
    sa.Column('extra_docker_args', sa.JSON(), nullable=True),
    sa.Column('volumes', sa.JSON(), nullable=True),
    sa.Column('profile_mount', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('internal_port', sa.Integer(), nullable=False),
    sa.Column('internal_protocol', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('category', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=True),
    sa.Column('session_config', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_service_templates_owner_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_templates'))
    )
    op.create_index(op.f('ix_service_templates_name'), 'service_templates', ['name'], unique=True)
    op.create_index(op.f('ix_service_templates_owner_id'), 'service_templates', ['owner_id'], unique=False)
    op.create_table('user_groups',
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('group_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_user_groups_group_id_groups')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_groups_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'group_id', name=op.f('pk_user_groups'))
    )
    op.create_table('workstation_enrollment_tokens',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_workstation_enrollment_tokens_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workstation_enrollment_tokens'))
    )
    op.create_index(op.f('ix_workstation_enrollment_tokens_token_hash'), 'workstation_enrollment_tokens', ['token_hash'], unique=True)
    op.create_table('workstations',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('subdomain', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('hostname', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('lan_ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('protocol', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_server', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('gpu_info', sa.JSON(), nullable=True),
    sa.Column('os_info', sa.JSON(), nullable=True),
    sa.Column('agent_version', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('agent_token_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('selkies_password_enc', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('stream_settings', sa.JSON(), nullable=True),
    sa.Column('all_users', sa.Boolean(), nullable=False),
    sa.Column('icon', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('update_target', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('update_state', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('update_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('update_at', sa.DateTime(), nullable=True),
    sa.Column('last_heartbeat', sa.DateTime(), nullable=True),
    sa.Column('last_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('active_connections', sa.Integer(), nullable=False),
    sa.Column('occupied_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('occupied_at', sa.DateTime(), nullable=True),
    sa.Column('disconnect_pending', sa.Boolean(), nullable=False),
    sa.Column('idle_disconnect_sent', sa.Boolean(), nullable=False),
    sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_workstations_created_by_users')),
    sa.ForeignKeyConstraint(['occupied_by'], ['users.id'], name=op.f('fk_workstations_occupied_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workstations'))
    )
    op.create_index(op.f('ix_workstations_agent_token_hash'), 'workstations', ['agent_token_hash'], unique=False)
    op.create_index(op.f('ix_workstations_subdomain'), 'workstations', ['subdomain'], unique=True)
    op.create_table('instances',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('template_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('owner_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('subdomain', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('container_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status_detail', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('env_overrides', sa.JSON(), nullable=True),
    sa.Column('volume_names', sa.JSON(), nullable=True),
    sa.Column('profile_volume', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('gpu', sa.Boolean(), nullable=True),
    sa.Column('notice', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('stopped_at', sa.DateTime(), nullable=True),
    sa.Column('last_activity', sa.DateTime(), nullable=True),
    sa.Column('session_config', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_instances_owner_id_users')),
    sa.ForeignKeyConstraint(['template_id'], ['service_templates.id'], name=op.f('fk_instances_template_id_service_templates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instances'))
    )
    op.create_index(op.f('ix_instances_owner_id'), 'instances', ['owner_id'], unique=False)
    op.create_index(op.f('ix_instances_subdomain'), 'instances', ['subdomain'], unique=True)
    op.create_table('turn_usage',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('month', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('workstation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_turn_usage_user_id_users')),
    sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], name=op.f('fk_turn_usage_workstation_id_workstations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_turn_usage')),
    sa.UniqueConstraint('month', 'workstation_id', 'user_id', name='uq_turn_usage')
    )
    op.create_index(op.f('ix_turn_usage_month'), 'turn_usage', ['month'], unique=False)
    op.create_table('user_profiles',
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('template_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('volume_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['service_templates.id'], name=op.f('fk_user_profiles_template_id_service_templates')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_profiles_user_id_users')),
    sa.PrimaryKeyConstraint('user_id', 'template_id', name=op.f('pk_user_profiles'))
    )
    op.create_table('workstation_access',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workstation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_workstation_access_user_id_users')),
    sa.ForeignKeyConstraint(['workstation_id'], ['workstations.id'], name=op.f('fk_workstation_access_workstation_id_workstations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workstation_access')),
    sa.UniqueConstraint('workstation_id', 'user_id', name='uq_workstation_user')
    )
    op.create_index(op.f('ix_workstation_access_user_id'), 'workstation_access', ['user_id'], unique=False)
    op.create_index(op.f('ix_workstation_access_workstation_id'), 'workstation_access', ['workstation_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_workstation_access_workstation_id'), table_name='workstation_access')
    op.drop_index(op.f('ix_workstation_access_user_id'), table_name='workstation_access')
    op.drop_table('workstation_access')
    op.drop_table('user_profiles')
    op.drop_index(op.f('ix_turn_usage_month'), table_name='turn_usage')
    op.drop_table('turn_usage')
    op.drop_index(op.f('ix_instances_subdomain'), table_name='instances')
    op.drop_index(op.f('ix_instances_owner_id'), table_name='instances')
    op.drop_table('instances')
    op.drop_index(op.f('ix_workstations_subdomain'), table_name='workstations')
    op.drop_index(op.f('ix_workstations_agent_token_hash'), table_name='workstations')
    op.drop_table('workstations')
    op.drop_index(op.f('ix_workstation_enrollment_tokens_token_hash'), table_name='workstation_enrollment_tokens')
    op.drop_table('workstation_enrollment_tokens')
    op.drop_table('user_groups')
    op.drop_index(op.f('ix_service_templates_owner_id'), table_name='service_templates')
    op.drop_index(op.f('ix_service_templates_name'), table_name='service_templates')
    op.drop_table('service_templates')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_invites_token_hash'), table_name='invites')
    op.drop_table('invites')
    op.drop_index(op.f('ix_federated_identities_user_id'), table_name='federated_identities')
    op.drop_index(op.f('ix_federated_identities_subject'), table_name='federated_identities')
    op.drop_index(op.f('ix_federated_identities_provider'), table_name='federated_identities')
    op.drop_table('federated_identities')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('turn_usage_day')
    op.drop_table('system_settings')
    op.drop_index(op.f('ix_stream_sessions_user_id'), table_name='stream_sessions')
    op.drop_index(op.f('ix_stream_sessions_target_id'), table_name='stream_sessions')
    op.drop_index(op.f('ix_stream_sessions_started_at'), table_name='stream_sessions')
    op.drop_table('stream_sessions')
    op.drop_table('session_events')
    op.drop_table('service_presets')
    op.drop_table('revoked_access_tokens')
    op.drop_index(op.f('ix_pulled_images_image'), table_name='pulled_images')
    op.drop_table('pulled_images')
    op.drop_index(op.f('ix_proxied_services_slug'), table_name='proxied_services')
    op.drop_table('proxied_services')
    op.drop_index(op.f('ix_oauth_providers_name'), table_name='oauth_providers')
    op.drop_table('oauth_providers')
    op.drop_index(op.f('ix_mount_jobs_service_id'), table_name='mount_jobs')
    op.drop_table('mount_jobs')
    op.drop_table('metric_hours')
    op.drop_index(op.f('ix_groups_name'), table_name='groups')
    op.drop_table('groups')
    op.drop_table('banned_ip')
    op.drop_index(op.f('ix_audit_log_user_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_ts'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
