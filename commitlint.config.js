// subject-case off: subjects often start with identifiers (AbuseStore,
// AlertmanagerConfig, POST /api/...), which config-conventional rejects as
// sentence-case. Inherited dev history cannot be rewritten in sync PRs (#343).
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: { 'subject-case': [0] },
};
