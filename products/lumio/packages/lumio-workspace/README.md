# lumio-workspace

Optional Python 3.14 deployment package for one owner-managed Lumio workspace. It serves an explicitly configured, immutable Published Version through authenticated Streamable HTTP MCP and keeps browser sessions separate from Pi API access tokens.

This W1 slice provides only `workspace_status`, `read_knowledge`, and `search_knowledge`. It does not upload, initialize, contribute, review, admit, or publish content. Live local-token/private-HTTPS client interoperability and the deferred live Entra leg remain unqualified until their owner-approved fixtures are run.

See [Shared workspace how-to](../../docs/howto-shared-workspace.md) for registration, configuration, owner bootstrap, and client connection.

## Authentication mode

Set `LUMIO_WORKSPACE_AUTH_MODE` explicitly to `entra` or `local-token`. Invalid or missing configuration fails closed. Entra mode retains the existing tenant, audience, client, and browser OIDC settings. Local-token mode does not require those Entra settings and never becomes an automatic fallback for failed Entra authentication.

Local users occupy the separate `local` identity namespace; their records and memberships do not remap existing Entra `tid`/`oid` identities. Membership and credentials are independent. The additive private SQLite state stores only SHA-256 credential hashes, lifecycle metadata, and opaque browser sessions.

With `LUMIO_WORKSPACE_ID` and `LUMIO_WORKSPACE_STATE_PATH` set, an operator can run:

```sh
lumio-workspace local-user create --user-id USER_ID
lumio-workspace local-membership grant --user-id USER_ID
lumio-workspace local-token issue --user-id USER_ID --purpose api --expires-at UNIX_SECONDS
lumio-workspace local-token issue --user-id USER_ID --purpose browser --expires-at UNIX_SECONDS
```

Issuance prints a credential ID and the raw credential once. Deliver it through an operator-controlled secure mechanism, never chat, URLs, tracked files, or logs. Rotate by issuing a new credential before revoking the old credential ID:

```sh
lumio-workspace local-token revoke --credential-id CREDENTIAL_ID
lumio-workspace local-user disable --user-id USER_ID
lumio-workspace local-membership revoke --user-id USER_ID
```

API credentials work only as API bearer tokens. Browser credentials work only in the same-origin HTTPS form POST at `/auth/login`; the GET form is inert and the raw credential is never placed in a URL. The resulting opaque server-managed session retains its source credential ID. Expiry, revocation, and user disable are checked on subsequent API/browser use, while membership removal is enforced independently.

The existing Entra `grant` and `revoke` commands still require `LUMIO_WORKSPACE_TENANT_ID` and `--object-id`.
