-- Schema of an old release (d349559, 2026-10-19): SQLModel create_all output.
-- Used by tests/test_db_startup.py to prove the one-time Alembic stamp keeps data.
CREATE TABLE audit_log (
	id INTEGER NOT NULL, 
	ts DATETIME NOT NULL, 
	user_id VARCHAR, 
	actor_ip VARCHAR, 
	action VARCHAR NOT NULL, 
	resource VARCHAR, 
	detail JSON, 
	PRIMARY KEY (id)
);
CREATE TABLE banned_ip (
	ip VARCHAR NOT NULL, 
	reason VARCHAR NOT NULL, 
	banned_at DATETIME NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (ip)
);
CREATE TABLE federated_identities (
	id VARCHAR NOT NULL, 
	user_id VARCHAR NOT NULL, 
	provider VARCHAR NOT NULL, 
	subject VARCHAR NOT NULL, 
	email VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_provider_subject UNIQUE (provider, subject), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE TABLE groups (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE instances (
	id VARCHAR NOT NULL, 
	template_id VARCHAR NOT NULL, 
	owner_id VARCHAR, 
	name VARCHAR NOT NULL, 
	subdomain VARCHAR NOT NULL, 
	container_id VARCHAR, 
	status VARCHAR NOT NULL, 
	error_message VARCHAR, 
	env_overrides JSON, 
	volume_names JSON, 
	created_at DATETIME NOT NULL, 
	started_at DATETIME, 
	stopped_at DATETIME, 
	last_activity DATETIME, 
	session_config JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(template_id) REFERENCES service_templates (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);
CREATE TABLE invites (
	id VARCHAR NOT NULL, 
	token_hash VARCHAR NOT NULL, 
	email VARCHAR, 
	role VARCHAR NOT NULL, 
	created_by VARCHAR NOT NULL, 
	expires_at DATETIME, 
	used_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);
CREATE TABLE mount_jobs (
	id VARCHAR NOT NULL, 
	service_id VARCHAR NOT NULL, 
	state VARCHAR NOT NULL, 
	steps JSON, 
	changes JSON, 
	backup_dir VARCHAR, 
	changed BOOLEAN NOT NULL, 
	log_excerpt VARCHAR, 
	created_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE TABLE oauth_providers (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	display_label VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	issuer_url VARCHAR, 
	authorize_url VARCHAR, 
	token_url VARCHAR, 
	userinfo_url VARCHAR, 
	client_id VARCHAR NOT NULL, 
	client_secret_enc VARCHAR NOT NULL, 
	scopes VARCHAR NOT NULL, 
	icon_url VARCHAR, 
	trust_email BOOLEAN NOT NULL, 
	allow_signup BOOLEAN NOT NULL, 
	auto_promote_admins BOOLEAN NOT NULL, 
	role_map JSON, 
	enabled BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE proxied_services (
	id VARCHAR NOT NULL, 
	slug VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	icon VARCHAR, 
	kind VARCHAR NOT NULL, 
	upstream_url VARCHAR, 
	container VARCHAR, 
	container_port INTEGER, 
	upstream_fallback VARCHAR, 
	mount_mode VARCHAR NOT NULL, 
	auth_mode VARCHAR NOT NULL, 
	bypass_rules JSON, 
	allowed_groups JSON, 
	verify_tls BOOLEAN NOT NULL, 
	upstream_is_proxy BOOLEAN NOT NULL, 
	health_path VARCHAR, 
	health_status VARCHAR NOT NULL, 
	health_checked_at DATETIME, 
	preset_id VARCHAR, 
	enabled BOOLEAN NOT NULL, 
	mount_managed BOOLEAN NOT NULL, 
	icon_custom BOOLEAN NOT NULL, 
	pass_identity BOOLEAN NOT NULL, 
	frame_ok BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE pulled_images (
	id VARCHAR NOT NULL, 
	image VARCHAR NOT NULL, 
	size_mb INTEGER, 
	pulled_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE refresh_tokens (
	jti VARCHAR NOT NULL, 
	user_id VARCHAR NOT NULL, 
	family_id VARCHAR NOT NULL, 
	expires_at DATETIME NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	user_agent VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (jti), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE TABLE revoked_access_tokens (
	jti VARCHAR NOT NULL, 
	expires_at DATETIME NOT NULL, 
	revoked_at DATETIME NOT NULL, 
	PRIMARY KEY (jti)
);
CREATE TABLE service_presets (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	icon VARCHAR, 
	default_port INTEGER, 
	mount_mode VARCHAR NOT NULL, 
	auth_mode VARCHAR NOT NULL, 
	bypass_rules JSON, 
	health_path VARCHAR, 
	verify_tls BOOLEAN NOT NULL, 
	base_url_hint VARCHAR, 
	warnings JSON, 
	subpath JSON, 
	PRIMARY KEY (id)
);
CREATE TABLE service_templates (
	id VARCHAR NOT NULL, 
	owner_id VARCHAR, 
	name VARCHAR NOT NULL, 
	display_name VARCHAR NOT NULL, 
	image VARCHAR NOT NULL, 
	icon VARCHAR, 
	description VARCHAR, 
	env_vars JSON, 
	gpu_enabled BOOLEAN NOT NULL, 
	gpu_count INTEGER NOT NULL, 
	memory_limit VARCHAR, 
	cpu_limit VARCHAR, 
	shm_size VARCHAR, 
	dind BOOLEAN NOT NULL, 
	cap_add JSON, 
	security_opt JSON, 
	tls_skip_verify BOOLEAN NOT NULL, 
	shared BOOLEAN NOT NULL, 
	restart_policy VARCHAR NOT NULL, 
	read_only_rootfs BOOLEAN NOT NULL, 
	tmpfs JSON, 
	extra_hosts JSON, 
	ulimits JSON, 
	extra_ports JSON, 
	entrypoint JSON, 
	command JSON, 
	devices JSON, 
	privileged BOOLEAN NOT NULL, 
	extra_docker_args JSON, 
	volumes JSON, 
	internal_port INTEGER NOT NULL, 
	internal_protocol VARCHAR NOT NULL, 
	category VARCHAR, 
	tags JSON, 
	session_config JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);
CREATE TABLE session_events (
	id INTEGER NOT NULL, 
	instance_id VARCHAR NOT NULL, 
	event_type VARCHAR NOT NULL, 
	details JSON, 
	timestamp DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(instance_id) REFERENCES instances (id)
);
CREATE TABLE system_settings (
	"key" VARCHAR NOT NULL, 
	value JSON, 
	updated_at DATETIME NOT NULL, 
	updated_by VARCHAR, 
	PRIMARY KEY ("key")
);
CREATE TABLE user_groups (
	user_id VARCHAR NOT NULL, 
	group_id VARCHAR NOT NULL, 
	PRIMARY KEY (user_id, group_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(group_id) REFERENCES groups (id)
);
CREATE TABLE users (
	id VARCHAR NOT NULL, 
	username VARCHAR NOT NULL, 
	email VARCHAR, 
	password_hash VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	must_change_pw BOOLEAN NOT NULL, 
	token_version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_login DATETIME, 
	failed_count INTEGER NOT NULL, 
	locked_until DATETIME, 
	open_workspaces VARCHAR, 
	open_apps VARCHAR, 
	PRIMARY KEY (id)
);
CREATE TABLE workstation_access (
	id INTEGER NOT NULL, 
	workstation_id VARCHAR NOT NULL, 
	user_id VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workstation_user UNIQUE (workstation_id, user_id), 
	FOREIGN KEY(workstation_id) REFERENCES workstations (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE TABLE workstation_enrollment_tokens (
	id VARCHAR NOT NULL, 
	token_hash VARCHAR NOT NULL, 
	created_by VARCHAR NOT NULL, 
	expires_at DATETIME NOT NULL, 
	used_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);
CREATE TABLE workstations (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	subdomain VARCHAR NOT NULL, 
	hostname VARCHAR NOT NULL, 
	lan_ip VARCHAR NOT NULL, 
	port INTEGER NOT NULL, 
	protocol VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	display_server VARCHAR NOT NULL, 
	gpu_info JSON, 
	os_info JSON, 
	agent_version VARCHAR NOT NULL, 
	agent_token_hash VARCHAR NOT NULL, 
	selkies_password_enc VARCHAR NOT NULL, 
	stream_settings JSON, 
	all_users BOOLEAN NOT NULL, 
	icon VARCHAR, 
	last_heartbeat DATETIME, 
	last_error VARCHAR, 
	active_connections INTEGER NOT NULL, 
	occupied_by VARCHAR, 
	occupied_at DATETIME, 
	disconnect_pending BOOLEAN NOT NULL, 
	idle_disconnect_sent BOOLEAN NOT NULL, 
	created_by VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(occupied_by) REFERENCES users (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);
CREATE INDEX ix_audit_log_action ON audit_log (action);
CREATE INDEX ix_audit_log_ts ON audit_log (ts);
CREATE INDEX ix_audit_log_user_id ON audit_log (user_id);
CREATE INDEX ix_federated_identities_provider ON federated_identities (provider);
CREATE INDEX ix_federated_identities_subject ON federated_identities (subject);
CREATE INDEX ix_federated_identities_user_id ON federated_identities (user_id);
CREATE UNIQUE INDEX ix_groups_name ON groups (name);
CREATE INDEX ix_instances_owner_id ON instances (owner_id);
CREATE UNIQUE INDEX ix_instances_subdomain ON instances (subdomain);
CREATE UNIQUE INDEX ix_invites_token_hash ON invites (token_hash);
CREATE INDEX ix_mount_jobs_service_id ON mount_jobs (service_id);
CREATE UNIQUE INDEX ix_oauth_providers_name ON oauth_providers (name);
CREATE UNIQUE INDEX ix_proxied_services_slug ON proxied_services (slug);
CREATE UNIQUE INDEX ix_pulled_images_image ON pulled_images (image);
CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE UNIQUE INDEX ix_service_templates_name ON service_templates (name);
CREATE INDEX ix_service_templates_owner_id ON service_templates (owner_id);
CREATE INDEX ix_users_email ON users (email);
CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE INDEX ix_workstation_access_user_id ON workstation_access (user_id);
CREATE INDEX ix_workstation_access_workstation_id ON workstation_access (workstation_id);
CREATE UNIQUE INDEX ix_workstation_enrollment_tokens_token_hash ON workstation_enrollment_tokens (token_hash);
CREATE INDEX ix_workstations_agent_token_hash ON workstations (agent_token_hash);
CREATE UNIQUE INDEX ix_workstations_subdomain ON workstations (subdomain);
INSERT INTO users (id, username, email, password_hash, role, is_active, must_change_pw, created_at, token_version, failed_count) VALUES ('u1', 'alice', 'a@x.test', 'hash1', 'admin', 1, 0, '2026-06-01 10:00:00.000000', 3, 0);
INSERT INTO users (id, username, email, password_hash, role, is_active, must_change_pw, created_at, token_version, failed_count) VALUES ('u2', 'bob', NULL, 'hash2', 'user', 1, 1, '2026-06-02 11:30:00.000000', 0, 2);
INSERT INTO service_templates (id, name, display_name, image, gpu_enabled, gpu_count, dind, tls_skip_verify, internal_port, internal_protocol, created_at, updated_at, shared, restart_policy, read_only_rootfs, privileged) VALUES ('t1', 'desk', 'Desktop', 'img:1', 0, 0, 0, 0, 3000, 'http', '2026-06-01 10:00:00.000000', '2026-06-01 10:00:00.000000', 1, 'unless-stopped', 0, 1);
