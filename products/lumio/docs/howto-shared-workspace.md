# Shared workspace: local tokens, Entra, and Pi (W1–W4)

**Accepted interim limitation — 2026-11-05:** The owner explicitly accepted the current API-token exposure for continued development, then authorized commit/merge/push and cleanup in BB `thr_26ccqihn5b`. Pi's default shell inherits its process environment: a model-callable shell or equivalent local tool can expose `LUMIO_WORKSPACE_API_TOKEN` in tool output, session history and model requests. The placeholder header alone does not isolate that secret. Until supported host isolation is qualified, use synthetic credentials/data only; do not claim secret isolation or real-user/private-HTTPS qualification. Browser credentials remain forbidden in Pi. This is a documented accepted development risk, not a fixed defect, a production-use grant, or completion of the remaining live checks.

This guide configures authenticated workspace access and the synthetic document contribution, review, and recovery path through W4. Local-token is the interim mode; the existing Entra registration and OAuth path remains a deferred option. Neither mode is live-qualified by this document.

Live interoperability remains **blocked** until the owner supplies approved synthetic local users, private HTTPS, two human participants, and installed Pi. Live Entra additionally requires the approved tenant fixture. No tenant or local-token live leg has passed merely because the automated boundary checks pass.

## 1. Select the authentication mode explicitly

Set `LUMIO_WORKSPACE_AUTH_MODE` to `local-token` or `entra` on both the service and Pi client. Missing or invalid service configuration fails closed. Local mode needs no Entra settings; failed or missing Entra authentication never selects local-token automatically. Switching modes is an operator action and does not map identities or migrate permissions.

Local users and Entra `(tid, oid)` identities are distinct. Credentials do not grant workspace membership by themselves. Pi receives only its user's API credential. A separate browser sign-in credential creates the browser session; neither browser credentials nor session cookies may enter Pi, prompts, model context, MCP results, logs, URLs, or tracked files.

## 2. Configure the service

Publish the Knowledge Base through native Lumio admission first, then point the service only at that publication destination. Optionally pin an exact immutable version; without a pin, each operation resolves the current pointer once.

Common read-only settings:

```sh
export LUMIO_WORKSPACE_ID='WORKSPACE_ID'
export LUMIO_WORKSPACE_EXTERNAL_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_PUBLISHED_PATH='/private/published-kb'
export LUMIO_WORKSPACE_PUBLISHED_VERSION='OPTIONAL_EXACT_VERSION'
export LUMIO_WORKSPACE_STATE_PATH='/private/workspace/state.sqlite3'
```

These settings alone do not enable setup, upload, contribution, or review. For that authoring-enabled path, also configure the service with the native authoring KB and private resources:

```sh
export LUMIO_WORKSPACE_AUTHORING_PATH='/private/authoring-repo/kb'
export LUMIO_WORKSPACE_PRIVATE_PROFILE='/private/workspace/profile.json'
export LUMIO_WORKSPACE_PRIVATE_ROOT='/private/workspace/operations'
# Required for new-empty setup; optional for an adopted KB, where it must match its manifest:
export LUMIO_WORKSPACE_NAMESPACE='urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210'
```

For this synthetic local configuration, the server-only private profile at the selected path contains:

```json
{
  "schema_version": 1,
  "namespace": "urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210",
  "source_registry": "/private/workspace/registry",
  "retention": "required",
  "artifact_store": {"kind": "local", "root": "/private/workspace/artifacts"}
}
```

Keep the profile, Source Registry, artifact store, operational directory, originals, and credentials outside the content repository and inaccessible to Pi. An existing adopted target must have a valid committed native Authoring Revision, `lumio.yaml`, `.lumio-authoring.yaml`, a matching namespace, and resolvable private registry/artifact resources. Its published destination must come from native admission of that actual history; setup does not invent ancestry or publish a baseline. New-empty setup requires the explicit namespace. A nonempty unadopted target is refused as `adoption_required` without mutation; this guide does not provide native adoption for it.

After the users and capabilities below are provisioned, the designated owner opens `https://WORKSPACE_HOST/setup` with their separate browser session. The GET displays the exact setup preview and readiness facts; the owner checks them and submits the same-origin protected form POST to apply that preview. Neither Pi nor an API token can perform this owner confirmation.

For local-token mode, explicitly set:

```sh
export LUMIO_WORKSPACE_AUTH_MODE='local-token'
```

For Entra mode, explicitly set the mode and retained tenant/client settings:

```sh
export LUMIO_WORKSPACE_AUTH_MODE='entra'
export LUMIO_WORKSPACE_TENANT_ID='TENANT_ID'
export LUMIO_WORKSPACE_API_AUDIENCE='WEB_API_APPLICATION_ID'
export LUMIO_WORKSPACE_PI_CLIENT_ID='PUBLIC_PI_APPLICATION_ID'
export LUMIO_WORKSPACE_BROWSER_CLIENT_ID='WEB_API_APPLICATION_ID'
export LUMIO_WORKSPACE_BROWSER_CLIENT_SECRET='SERVER_ONLY_SECRET'
export LUMIO_WORKSPACE_BROWSER_REDIRECT_URI='https://WORKSPACE_HOST/auth/callback'
```

Keep the state directory private and owner-only. Do not put configuration or secrets in prompts, source documents, tracked files, MCP results, or Pi settings. Start with `python -m lumio_workspace serve`; the default listener is `127.0.0.1:8000` behind private HTTPS.

## 3. Bootstrap local users and purpose-separated credentials

With `LUMIO_WORKSPACE_ID` and `LUMIO_WORKSPACE_STATE_PATH` set, the administrator creates each stable local user and independently grants membership:

```sh
lumio-workspace local-user create --user-id USER_ID
lumio-workspace local-membership grant --user-id USER_ID
```

The membership command above grants only the default `read` capability. For the authoring-enabled path, provision each capability explicitly to the designated person; no first-login promotion or grant inferred from authentication, contribution, or review is supported:

```sh
lumio-workspace local-membership grant --user-id OWNER_ID --capability setup
lumio-workspace local-membership grant --user-id CONTRIBUTOR_ID --capability contribute
lumio-workspace local-membership grant --user-id REVIEWER_ID --capability review
# Optional, and independent of review:
lumio-workspace local-membership grant --user-id REVIEWER_ID --capability inspect_source
```

Issue separate expiring API and browser credentials for each person:

```sh
lumio-workspace local-token issue --user-id USER_ID --purpose api --expires-at UNIX_SECONDS
lumio-workspace local-token issue --user-id USER_ID --purpose browser --expires-at UNIX_SECONDS
```

Issuance prints the credential ID and raw credential once. Deliver each credential only to its intended person through the operator-controlled secure mechanism. An agent must not issue, capture, or receive a human's browser credential. API tokens authenticate `/mcp` only; browser tokens are accepted only by the same-origin HTTPS login form POST. Neither credential proves human presence or permits an agent to perform human approval.

Rotate by issuing a replacement before revoking the old credential ID. Revoke credentials, disable users, and remove membership independently:

```sh
lumio-workspace local-token revoke --credential-id CREDENTIAL_ID
lumio-workspace local-user disable --user-id USER_ID
lumio-workspace local-membership revoke --user-id USER_ID
```

Every API request checks credential purpose, expiry, revocation, and user-enabled state, then checks current workspace membership. Browser sessions retain their source credential provenance and are refused after that credential expires or is revoked or the user is disabled. API-token revocation does not revoke an unrelated browser credential, and vice versa. Membership removal blocks both routes independently of otherwise valid credentials.

## 4. Preserve the deferred Entra registration guide

Use this section only for an explicitly selected Entra deployment and its separately authorized live fixture. Live Entra qualification is not claimed or completed here.

### Confidential web/API application

1. Create a single-tenant application registration for the workspace service. Set `accessTokenAcceptedVersion` to `2`.
2. Add a **Web** redirect URI exactly matching `https://WORKSPACE_HOST/auth/callback`. Create its client secret only in Entra and deliver it to the server through the owner-controlled secret mechanism. Pi never receives this secret.
3. Under **Expose an API**, set the Application ID URI to `api://WEB_API_APPLICATION_ID` and add the delegated scope `Knowledge.Read` with a readable admin/user description such as “Read admitted workspace knowledge.” For v2 access tokens, configure the audience as the API application client ID GUID `WEB_API_APPLICATION_ID`; Microsoft always puts that client ID in `aud`. Keep the `api://` URI for the delegated scope, not as the expected v2 audience.
4. Grant the public Pi application below delegated permission for `Knowledge.Read` and complete any tenant-required consent. No broad directory, mail, document, or repository permission is needed.

The browser uses authorization-code OIDC with PKCE and `openid profile`; its ID token creates only the server-managed browser session. The Pi API flow uses a distinct resource-scoped access token. Neither credential substitutes for the other, and neither grants workspace membership by itself.

### Public Pi application

1. Create a separate single-tenant **public client** registration for Pi. Do not create a client secret.
2. Register exactly `http://127.0.0.1:8765/callback` as a loopback redirect URI and enable the public-client/native flow required by Entra. If another port is selected, change both the registration and `LUMIO_WORKSPACE_CALLBACK_PORT`.
3. Add the delegated `Knowledge.Read` permission for the web/API application and complete required consent.

Pi uses authorization code + PKCE. The service validates RS256 signature, expiry, tenant-scoped issuer, API audience, `tid`, permitted public-client `azp`, and `Knowledge.Read` scope. Browser and API identities are associated only by validated `(tid, oid)`, never email.

Required discovery URL:

```text
https://login.microsoftonline.com/TENANT_ID/v2.0/.well-known/openid-configuration
```

Obtain each person’s Entra **object ID** through the operator’s normal directory administration path, then grant only W1 read capability:

```sh
python -m lumio_workspace grant --object-id 'ENTRA_PERSON_OBJECT_ID'
```

Remove access with `revoke --object-id ...`. Every MCP read/search/status operation checks current SQLite membership before resolving published content. Entra account-disable timing follows provider token/session lifetimes.

## 5. Private connectivity

The operator provides private HTTPS for `https://WORKSPACE_HOST`. The browser and Pi must reach that host; run the ASGI process on its private loopback/socket behind the configured HTTPS boundary. Do not expose a public content endpoint or substitute another identity provider. Entra mode additionally requires browser/Pi access to Microsoft Entra endpoints and service access to Entra discovery, token, and JWKS endpoints.

## 6. Connect Pi

Load `products/lumio/clients/pi-workspace` as a trusted Pi extension package. In local-token mode, deliver the current user's API token into Pi's operator-controlled process environment, not into chat or tracked configuration, and set:

```sh
export LUMIO_WORKSPACE_AUTH_MODE='local-token'
export LUMIO_WORKSPACE_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_API_TOKEN='USER_API_TOKEN'
export LUMIO_WORKSPACE_ALLOWED_MODELS='APPROVED_PROVIDER/APPROVED_MODEL'
```

The extension registers `Authorization: Bearer ${LUMIO_WORKSPACE_API_TOKEN}` as Pi's supported placeholder configuration. Pi resolves it only for the MCP HTTP transport; the extension does not place the resolved token in status, tool descriptions/results, session history, logs, or URLs.

For Entra mode, retain the OAuth settings instead:

```sh
export LUMIO_WORKSPACE_AUTH_MODE='entra'
export LUMIO_WORKSPACE_URL='https://WORKSPACE_HOST'
export LUMIO_WORKSPACE_PI_CLIENT_ID='PUBLIC_PI_APPLICATION_ID'
export LUMIO_WORKSPACE_SCOPE='api://WEB_API_APPLICATION_ID/Knowledge.Read'
export LUMIO_WORKSPACE_AUTH_METADATA_URL='https://login.microsoftonline.com/TENANT_ID/v2.0/.well-known/openid-configuration'
export LUMIO_WORKSPACE_ALLOWED_MODELS='APPROVED_PROVIDER/APPROVED_MODEL'
# Optional; must match the registered loopback callback:
export LUMIO_WORKSPACE_CALLBACK_PORT='8765'
```

Reload Pi and run `/workspace` to inspect configuration and model disclosure status, then `/mcp` to inspect `lumio-workspace`. Entra mode also uses `/mcp` for OAuth sign-in. The read tools are `workspace_status`, `read_knowledge`, and `search_knowledge`; contribution uses `read_source_material`, `prepare_contribution`, and actor-scoped `get_task`. No MCP tool grants browser approval.

The extension checks the exact provider/model before every workspace MCP call and rechecks after model changes; an empty or nonmatching allowlist blocks reads before content can be returned. After a successful workspace result, it also aborts any provider request that would carry retained workspace history to a nonallowed model, including after a model switch or session resume. Clean conversations without workspace results remain usable. This is trusted-client disclosure policy, not remote attestation.

## 7. Contribute documents and recover after restart

Use `/workspace-upload <source-id> <path> [retry=<key>]` for exact original bytes up to 25 MiB. Supported document inputs are UTF-8 `.txt`, `.md`, and `.markdown`, plus `.pdf` and `.docx`. Other formats, including legacy Word, are refused unless a separately approved task adds them. Upload retention is not extraction, review, admission, or publication.

From the **first upload attempt**, explicitly choose and retain `retry=<stable-key>` when interruption recovery matters, together with the exact bytes, source ID, and filename. If the option is omitted, the command generates an arbitrary key for that invocation; the immediate upload still works, but a key lost with an interrupted client cannot be reconstructed. A successful upload returns an **`upload_id`**, not a `task_id`.

After an interrupted upload, repeat `/workspace-upload` with the same key and exact source ID, filename, and bytes to recover the same `upload_id`. Do not call `get_task` with an `upload_id` or invent a task ID. Recovery is not possible from a lost key or lost/changed input; a changed input under the same key conflicts rather than silently replacing the original.

The service reuses the existing native processors: PDF uses LiteParse and retains only converter-supplied page numbers; DOCX uses AnyDoc and produces heading-based sections without invented page coordinates. Conversion retains the native 200,000-character, 200-section, 20-second, and archive bounds. Missing document extras, invalid input, conversion failure, and empty results are errors. `read_source_material` returns the actual processor and any `incomplete` truncation signal; the browser review shows the same conversion facts. Do not describe truncated output or coordinates the processor did not supply as complete or lossless.

For `prepare_contribution`, explicitly choose and retain a separate stable preparation `retry_key` and the exact request, including its recovered `upload_id` values, source intents, pages, and any continuation task. Preparation returns the actual **`task_id`**; retain it for actor-scoped `get_task` status. If preparation was interrupted before that ID was learned, repeat the same preparation with the same key and exact request to recover the identified task, then call `get_task` once the task exists. If the actual `task_id` is already known, inspect it with `get_task` before any further preparation. A prepared receipt alone is not activation.

The service reads persisted SQLite identity plus native commits, admission receipts, and the current pointer. A completed native publication is reported even when later bookkeeping failed. A historical publication's version and citations remain distinct from the current reader pointer, which may have advanced to a newer activation.

Recovery never blindly replays browser approval: changed candidates or bases require a fresh review, and stale, expired, revoked, or currently unauthorized browser actions cannot activate content. This synthetic guidance does not qualify the actual PDF/DOCX binary upload-to-review journey, which remains W6, or any live human/client milestone.

## 8. Sign in separately in the browser

Local browser status is at `https://WORKSPACE_HOST/workspace`. Opening `/auth/login` displays an inert form; the person enters their separate browser sign-in token into that same-origin HTTPS form POST. The local `/auth/callback` is 404. Entra mode instead retains `/auth/login` OIDC initiation and `/auth/callback`.

The browser receives only an opaque, Secure, HttpOnly, SameSite=Lax cookie; sign-in rotates that credential, and server-side deletion or the one-hour expiry refuses an old cookie. Browser sign-in and API access are independently checked against current membership. No browser action in W1 admits or publishes anything.

## 9. Qualification recipe — blocked pending authorized live fixture

This is a recipe, not evidence that the leg ran. The owner must separately authorize private HTTPS, a pinned synthetic publication, installed Pi, and two actual local human users with securely delivered purpose-separated credentials. One agent acting as both people does not prove human approval, and W3 retains exact human-admission proof.

1. Create two local users, grant only the intended reader membership, and issue distinct API/browser credentials to each person through the operator's secure delivery path.
2. Start the service in explicit `local-token` mode behind authorized private HTTPS with the pinned synthetic Published Version.
3. Have the intended user start installed Pi with their API token in the operator-controlled environment and the exact owner model allowlist. Through `/mcp`, call `read_knowledge` for the pinned title and verify the independently known synthetic sentinel. Check that the token is absent from model-facing requests, session history, status, tool results, logs, and URLs.
4. Have that person independently open the browser login over private HTTPS and sign in with their separate browser credential; verify `/workspace` without supplying any browser credential or cookie to Pi.
5. Remove membership and verify that a new Pi read and browser status are refused even though the credentials remain otherwise valid. Separately verify credential revocation/expiry and user disable behavior, then restore only the intended authorized state.
6. Select a forbidden provider/model and verify that new reads and requests carrying retained or derived workspace history are refused. Do not use real company data or real model-provider credentials in the synthetic fixture.

No tenant provisioning, live account use, real data, service exposure, or live interoperability claim is authorized by this W1 implementation. The Entra live leg remains deferred and requires its own approved tenant/registrations and human identities.
