# Workspace operations: run, back up, and restore the single-server workspace (W5)

This guide extends [howto-shared-workspace.md](howto-shared-workspace.md) (W1–W4:
configuration, credentials, contribution, review, restart recovery) with the
owner's operational recipe for the one-process private workspace service:
launch, shutdown/quiesce, backup, restore, service-binary rollback, and
authorized original deletion. It is a synthetic-development recipe; the
accepted interim limitation on API-token exposure in Pi still applies, and
nothing here is live-qualified.

## 1. One-process launch with an owner-supplied ingress

The service is one Python 3.14 process:

```sh
lumio-workspace serve --host 127.0.0.1 --port 8000
```

Run it on a private loopback or socket **behind the owner-supplied HTTPS
ingress** (for example a reverse proxy terminating TLS for
`https://WORKSPACE_HOST` and forwarding to the loopback listener). The service
checks `https` scheme and same-origin on browser POSTs; the ingress provides
the actual TLS boundary. No platform-specific cloud provisioning is implied or
supported.

Keep configuration in an owner-controlled secret/environment file (for example
`/private/workspace/workspace.env` with the `LUMIO_WORKSPACE_*` variables from
howto-shared-workspace.md) and load it through the process manager — a systemd
unit with `EnvironmentFile=`, or `set -a; . /private/workspace/workspace.env`
before `serve`. Credentials and secrets never live in prompts, tracked files,
or content.

## 2. Durable data root layout

Everything the workspace durably owns lives in one data root. The operational
tooling in `lumio_workspace.operations` treats it as these roles:

| Role | Path (convention) | Contents |
| --- | --- | --- |
| Operational state | `state.sqlite3` (+ `operation-locks/`) | memberships, local users/credentials, task operations, review actions, setup records, browser sessions |
| Private operational tree | `private/` | uploads, task worktrees, authored pages, controls, activation locks |
| Authoring repository | `authoring-repo/` | the Git authoring truth, including task branches and worktree metadata |
| Private profile | `profile.json` | source registry and artifact store references, retention |
| Source registry | `registry/` | private source history and bindings |
| Artifact store | `artifacts/` | private original bytes |
| Published destination | `published/` | immutable version trees, admission receipts, current pointer |
| Analytics (when enabled) | `analytics-project/`, `analytics-bindings.json` | the configured execution project and operator source bindings |

Nothing else is required to reconstruct the workspace. Credentials are hashes
in SQLite; raw tokens exist only where the operator issued them.

## 3. Shutdown and quiesce

The deployment has one writer process: **stopping the service is the quiesce.**
In-flight contribution/publication states are not lost — on restart, `get_task`
and browser review reconcile native state exactly as documented in
howto-shared-workspace.md §7 (retry keys recover identified operations; no
success is reported from half-finished work).

For backups, stop the service first. `operations backup` additionally acquires
the same mutation locks an activation takes, so any in-flight native mutation
either drains before the copy or blocks it.

## 4. Backup

With the service stopped and the launch environment loaded:

```sh
python -m lumio_workspace.operations backup --backup-root /private/backups/workspace-$(date -u +%Y%m%dT%H%M%SZ)
```

The backup is a complete, self-contained copy of every role in §2 plus a
`manifest.json` identifying the workspace. It covers Git, the private source
registry and artifact store (originals and derived data), immutable published
versions and receipts, and SQLite **together**, copied under the activation
locks. Move it to separate storage; a backup on the same volume as the data
root shares its failure domain.

## 5. Restore into a data root

Restore always materializes a **fresh** data root (the target must be new or
empty) — it never merges into a live root. Load the launch environment (it may
still point at the old root; only non-path facts are used) and run:

```sh
python -m lumio_workspace.operations restore --backup-root /private/backups/workspace-... --target-root /private/workspace-new
```

The command prints the rebased launch paths; put them into the environment
file, then start the service against the new root. The printed paths map to
exactly these environment variables:

| Printed path | Environment variable |
| --- | --- |
| `state_path=` | `LUMIO_WORKSPACE_STATE_PATH` |
| `authoring_path=` | `LUMIO_WORKSPACE_AUTHORING_PATH` |
| `published_path=` | `LUMIO_WORKSPACE_PUBLISHED_PATH` |
| `private_profile_path=` | `LUMIO_WORKSPACE_PRIVATE_PROFILE` |
| `private_root=` | `LUMIO_WORKSPACE_PRIVATE_ROOT` |
| `export LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH=` | `LUMIO_WORKSPACE_ANALYTICS_PROJECT_PATH` |
| `export LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS=` | `LUMIO_WORKSPACE_ANALYTICS_SOURCE_BINDINGS` |

When analytics is configured, the two analytics lines are printed as
ready-to-paste `export` assignments for the new data root. An owner
following this recipe literally copies every mapped variable into the
environment file and restarts the service against the restored copies.

**Disclosed restore boundary (analytics proposals):** restored Ariadne
proposal records retain their old absolute project identity, so native
proposal loading rejects the new project path even after the Git worktree
relinking below succeeds. Relinking keeps the copied worktrees valid Git
worktrees; it does not — and is not intended to — make pre-existing proposal
records loadable from the moved project. This is an honest boundary of the
restore recipe, not a data-loss claim: the project's Git history and
worktrees are intact, and new proposals at the restored root work normally.

Restore performs, in order:

1. Copies every role into the target root under the §2 convention.
2. Relinks moved task worktrees (the pending candidate worktrees stay
   resumable).
3. Rebases the private profile's registry/artifact references to the new root.
4. **Invalidates every outstanding browser review action** — pre-restore
   digests can never activate content afterwards; a pending candidate needs a
   fresh browser review.
5. **Deletes all browser sessions** — everyone signs in again.

Credentials are re-established **outside content**: token hashes travel in
SQLite with the backup, and each person signs in with their existing
operator-issued credential. If compromise is suspected, revoke and reissue
tokens with the `local-token` CLI; restoring a backup does not un-revoke
anything revoked before it was taken.

Because the moved root changes the setup attachment identity, the owner must
re-confirm setup once at `https://WORKSPACE_HOST/setup` before new
contributions, reviews, or activations are accepted. Reads of admitted content
work immediately after restore.

The restore recipe is exactly the path covered by
`tests/test_workspace_operations.py::test_restore_and_revocation_preserve_admitted_only_access`:
after restore, the admitted version stays the sole readable content, pending
candidates stay pending, pre-restore review actions cannot activate, and a
member removed through the owner's browser membership page is denied on both
API and browser routes.

## 6. Owner membership surface

The owner (the `setup` capability) manages membership in the browser at
`https://WORKSPACE_HOST/membership`: list local users and capabilities, and
grant or revoke `read`, `contribute`, and `review` per user with a same-origin
HTTPS form POST. Membership changes take effect on the next request.

**Original/source/data inspection (`inspect_source`) and owner setup transfer
stay separate explicit operator grants** — they are deliberately not available
on this page; use the `local-membership` CLI as in howto-shared-workspace.md §3.

## 7. Service-binary rollback

Rolling back the service binary (reinstalling the previous
`lumio-workspace` wheel) performs **no content migration in either
direction**: Git, registry, artifacts, publications, and SQLite keep their
bytes and schemas as they are. The operational store uses additive
`CREATE TABLE IF NOT EXISTS` provisioning, but a **newer** data root under an
**older** binary is unsupported — after running a new binary against a data
root, roll back by restoring the backup taken **before** the upgrade into a
fresh root (§5), not by downgrading in place. For that reason, take a backup
immediately before every service upgrade.

## 8. Authorized original deletion

There is **no automatic garbage collection and no total-erasure promise.**
Retained originals do not expire by themselves, and publication retirement
never deletes historical artifacts. The single authorized deletion path is
the native Lumio operation `delete_artifact_with_disclosure`
(owner-operated through the SDK's artifact-store tooling; not a contributor
tool). It takes the exact `source_id` and `content_hash` pair and:

- computes the affected Published Versions from the stored binding
  manifests **before** deleting, then deletes those artifact bytes and clears
  the registry binding, so metadata never claims a retained artifact the
  store no longer holds;
- performs **no retention pre-check and does not refuse** when admitted
  content is bound — the affected-version disclosure is returned by the
  operation itself; an owner who needs the list before deciding enumerates it
  first with the same helper (`affected_published_versions`); the versions
  themselves are not rewritten;
- leaves Git history, immutable published versions, receipts, and every
  backup untouched. Copies that remain in backups and immutable publications
  must be handled by rotating those artifacts under their own procedures.
  Report truthfully what remains; never claim compliant erasure of every
  immutable copy.

## 9. Limits

Single-writer, single-process, owner-operated. No cloud provisioning, no
distributed queue, no scheduled jobs, and no cross-workspace operations are
added by this guide. Analytics roots (§2) are included in backup/restore only
when analytics is configured in the launch environment.
