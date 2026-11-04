# Shared workspace: Entra and Pi (W1)

This guide configures the local W1 read slice: Entra identity, current workspace membership, and read/search of one existing Published Version through Streamable HTTP MCP. It does not configure upload, workspace setup, contribution, review, admission, or publication. Live interoperability remains **blocked** until the owner supplies an approved synthetic Entra/private-HTTPS fixture; this document is not evidence of a completed live leg.

## 1. Register the two single-tenant Entra applications

Use the owner-selected workforce tenant. Tenant IDs, application IDs, secrets, and hostnames below are operator inputs; do not commit them.

### Confidential web/API application

1. Create a single-tenant application registration for the workspace service. Set `accessTokenAcceptedVersion` to `2`.
2. Add a **Web** redirect URI exactly matching `https://WORKSPACE_HOST/auth/callback`. Create its client secret only in Entra and deliver it to the server through the owner-controlled secret mechanism. Pi never receives this secret.
3. Under **Expose an API**, set the Application ID URI to `api://WEB_API_APPLICATION_ID` and add the delegated scope `Knowledge.Read` with a readable admin/user description such as “Read admitted workspace knowledge.” The configured audience is then `api://WEB_API_APPLICATION_ID`.
4. Grant the public Pi application below delegated permission for `Knowledge.Read` and complete any tenant-required consent. No broad directory, mail, document, or repository permission is needed.

The browser uses authorization-code OIDC with PKCE and `openid profile`; its ID token creates only the server-managed browser session. The Pi API flow uses a distinct resource-scoped access token. Neither credential substitutes for the other, and neither grants workspace membership by itself.

### Public Pi application

1. Create a separate single-tenant **public client** registration for Pi. Do not create a client secret.
2. Register exactly `http://127.0.0.1:8765/callback` as a loopback redirect URI and enable the public-client/native flow required by Entra. If another port is selected, change both the registration and `LUMIO_WORKSPACE_CALLBACK_PORT`.
3. Add the delegated `Knowledge.Read` permission for the web/API application and complete required consent.

Pi uses authorization code + PKCE. The service validates RS256 signature, expiry, tenant-scoped issuer, API audience, `tid`, permitted public-client `azp`, and `Knowledge.Read` scope. Browser and API identities are associated only by validated `(tid, oid)`, never email.

## 2. Private connectivity

The operator provides private HTTPS for `https://WORKSPACE_HOST`. The browser must reach that host and Microsoft’s Entra endpoints; Pi must reach the workspace `/mcp` endpoint and Entra; the service must reach Entra discovery, token, and JWKS endpoints. Run the ASGI process on its private loopback/socket behind the configured HTTPS boundary. Do not expose a public content endpoint or substitute another identity provider.

Required discovery URL:

```text
https://login.microsoftonline.com/TENANT_ID/v2.0/.well-known/openid-configuration
```

## 3. Configure the service

Publish the Knowledge Base through native Lumio admission first, then point the service only at that publication destination. Optionally pin an exact immutable version; without a pin, each operation resolves the current pointer once.

```sh
export LUMIO_WORKSPACE_ID='WORKSPACE_ID'
export LUMIO_WORKSPACE_EXTERNAL_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_PUBLISHED_PATH='/private/published-kb'
export LUMIO_WORKSPACE_PUBLISHED_VERSION='OPTIONAL_EXACT_VERSION'
export LUMIO_WORKSPACE_STATE_PATH='/private/workspace/state.sqlite3'
export LUMIO_WORKSPACE_TENANT_ID='TENANT_ID'
export LUMIO_WORKSPACE_API_AUDIENCE='api://WEB_API_APPLICATION_ID'
export LUMIO_WORKSPACE_PI_CLIENT_ID='PUBLIC_PI_APPLICATION_ID'
export LUMIO_WORKSPACE_BROWSER_CLIENT_ID='WEB_API_APPLICATION_ID'
export LUMIO_WORKSPACE_BROWSER_CLIENT_SECRET='SERVER_ONLY_SECRET'
export LUMIO_WORKSPACE_BROWSER_REDIRECT_URI='https://WORKSPACE_HOST/auth/callback'
export LUMIO_WORKSPACE_SESSION_SECRET='SERVER_ONLY_SESSION_SECRET'
```

Keep the state directory private and owner-only. Do not put configuration or secrets in prompts, source documents, tracked files, MCP results, or Pi settings. Start with `python -m lumio_workspace serve`; the default listener is `127.0.0.1:8000` behind private HTTPS.

## 4. Bootstrap membership explicitly

Obtain each person’s Entra **object ID** through the operator’s normal directory administration path. First login and tenant membership do not create workspace access. The local owner grants only the W1 read capability:

```sh
python -m lumio_workspace grant --object-id 'ENTRA_PERSON_OBJECT_ID'
```

Remove access with `revoke --object-id ...`. Every MCP read/search/status operation checks current SQLite membership before resolving published content, so removal blocks new operations even while an Entra token remains cryptographically valid. Entra account-disable timing still follows provider token/session lifetimes.

Browser status is at `https://WORKSPACE_HOST/workspace`; `/auth/login` starts the separate browser OIDC flow. No browser action in W1 admits or publishes anything.

## 5. Connect Pi

Load `products/lumio/clients/pi-workspace` as a trusted Pi extension package and set:

```sh
export LUMIO_WORKSPACE_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_PI_CLIENT_ID='PUBLIC_PI_APPLICATION_ID'
export LUMIO_WORKSPACE_SCOPE='api://WEB_API_APPLICATION_ID/Knowledge.Read'
export LUMIO_WORKSPACE_AUTH_METADATA_URL='https://login.microsoftonline.com/TENANT_ID/v2.0/.well-known/openid-configuration'
export LUMIO_WORKSPACE_ALLOWED_MODELS='APPROVED_PROVIDER/APPROVED_MODEL'
# Optional; must match the registered loopback callback:
export LUMIO_WORKSPACE_CALLBACK_PORT='8765'
```

Reload Pi, run `/workspace` to inspect configuration and model disclosure status, then use `/mcp` to inspect `lumio-workspace` and sign in. The available read-only tools are `workspace_status`, `read_knowledge`, and `search_knowledge`. The extension checks the exact provider/model before every workspace MCP call and rechecks after model changes; an empty or nonmatching allowlist blocks reads before content can be returned. This is trusted-client disclosure policy, not remote attestation.

No tenant provisioning, live account use, real data, service exposure, or live interoperability claim is authorized by this W1 implementation. Qualification requires the owner-approved synthetic tenant/registrations, two human identities, private HTTPS, installed Pi, and a pinned synthetic published sentinel page.
