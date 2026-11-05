# lumio-workspace

Optional Python 3.14 deployment package for one owner-managed Lumio workspace. It serves an explicitly configured, immutable Published Version through authenticated Streamable HTTP MCP and keeps browser sessions separate from Pi API access tokens.

The W1 surface provides `workspace_status`, `read_knowledge`, and `search_knowledge`. The isolated W2 surface adds owner-confirmed native setup, exact-byte upload, normalized text/Markdown material, and pending native candidates. W3 adds a separate browser review of the exact native candidate and publication review; approval activates through native admission, while rejection and change requests do not. Reviewer and original-source inspection capabilities are independent of contribution and of each other. Live local-token/private-HTTPS client interoperability, the actual two-human journey, and the deferred live Entra leg remain unqualified until their owner-approved fixtures are run.

W2 supports only new-empty and already natively adopted Knowledge Bases. A nonempty unadopted target is refused as `adoption_required` without mutation; native adoption/preview remains open follow-up work. Setup and contribution require separate, explicitly provisioned capabilities; no first-login owner or promotion from read is inferred. Set `LUMIO_WORKSPACE_AUTHORING_PATH`, `LUMIO_WORKSPACE_PRIVATE_PROFILE`, and optionally `LUMIO_WORKSPACE_PRIVATE_ROOT` to enable them. New-empty setup also needs an explicit `LUMIO_WORKSPACE_NAMESPACE`. Uploads accept only `.txt`, `.md`, and `.markdown` originals up to 25 MiB.

For local-token mode, grant or revoke capabilities independently (the default remains `read`):

```sh
lumio-workspace local-membership grant --user-id OWNER_ID --capability setup
lumio-workspace local-membership grant --user-id CONTRIBUTOR_ID --capability contribute
lumio-workspace local-membership grant --user-id REVIEWER_ID --capability review
lumio-workspace local-membership grant --user-id REVIEWER_ID --capability inspect_source
lumio-workspace local-membership revoke --user-id CONTRIBUTOR_ID --capability contribute
lumio-workspace local-membership revoke --user-id REVIEWER_ID --capability review
lumio-workspace local-membership revoke --user-id REVIEWER_ID --capability inspect_source
```

Entra membership commands accept the same `--capability` option. Upload uses `POST /uploads` with an API credential and `application/octet-stream`; setup uses the separately browser-authenticated, same-origin `/setup` preview and POST. Contribution preparation selects and persists the authoring base server-side; an actor can edit its pending candidate through the opaque `continuation_task_id`, without a checkout or copied Git hash.

The `review_url` returned with a pending task opens an inert browser GET. A current reviewer capability is required to locate another contributor's candidate; ordinary `get_task` remains actor-scoped. Only a same-origin form POST from that separately authenticated reviewer can consume the one-use action binding. Original links additionally require `inspect_source`; `review` alone never returns original bytes. Decisions and source credentials are not placed in URLs or MCP results. An explicit `LUMIO_WORKSPACE_PUBLISHED_VERSION` reader pin remains unchanged by a new activation.

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

The existing Entra `grant` and `revoke` commands still require `LUMIO_WORKSPACE_TENANT_ID` and `--object-id`; omitting `--capability` preserves their original read-only behavior.
