# Keycloak admin client permissions

Controls: AC-2, AC-6. Decisions: ADR-0051 (D51), ADR-0082. Code: `backend/app/services/kc_admin.py`.

Styx talks to Keycloak with one confidential service-account client in the Styx realm (`KC_ADMIN_URL`, `KC_ADMIN_REALM`, `KC_ADMIN_CLIENT_ID`, `KC_ADMIN_CLIENT_SECRET`). It must not be a realm admin. Grant it fine-grained admin permissions only; do not assign it the `realm-admin` or `manage-realm` roles.

## Granted

| Capability | Keycloak permission (users resource, `manage-users` scope set) | Used by |
|---|---|---|
| Create user | `manage-users` (create) | `create_user` on provisioning |
| Update user, attributes (`posix_uid`, `edipi`, `card_uuid`) | `manage-users` | `update_user`, `set_attributes`, card binding |
| Read user attributes | `view-users` | `get_attributes` (merge before write) |
| Disable user (`enabled=false`) | `manage-users` | offboarding |
| Delete user | `manage-users` | 90-day account deletion (ADR-0073) |
| Add or remove membership in non-admin groups | `manage-membership` on those groups | `add_to_group`, `remove_from_group` |

Scope the group permission to the ordinary groups only, never the admin groups.

## Denied

- Role mapping: no `manage-realm`, no `map-roles` on users or groups, so it cannot grant a realm or client role.
- Admin groups: no membership permission on any group in `KEYCLOAK_ADMIN_GROUPS`. The client also refuses them in code (`add_to_group` raises), and the webhook returns 403.
- Realm settings, clients, identity providers, authentication flows, keys: no `manage-realm`, `manage-clients`, `manage-identity-providers`.
- Users in admin or break-glass groups: not covered by the users permission policy.
- Impersonation: no `impersonate` permission.

## Verify

After any realm change, check with the client's token: creating a user and adding it to an ordinary group succeeds; adding it to an admin group, mapping a role (`POST /users/{id}/role-mappings/realm`) and `PUT /` on the realm return 403. Keep the result as AC-6 evidence.

## Secret handling

`KC_ADMIN_CLIENT_SECRET` lives in OpenBao and reaches the pod through External Secrets (ADR-0042). It is never logged. Rotate it by regenerating the client secret in Keycloak, updating OpenBao, then restarting the backend.
