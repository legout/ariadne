---
status: accepted
---

# ADR-0027: Public Ariadne–Lumio monorepo with independent packages

The owner selected existing `legout/ariadne` as the target on 2026-10-21.
The owner subsequently required independent as well as combined use and accepted
revision 2 and its repository-name recommendation with “ok. passt” (2026-10-21).
The approved canonical target is `legout/ariadne-lumio`, by renaming the existing
repository; public package names remain unchanged. This is design approval,
not authorization to perform the external rename or migration. Observable
requirements are in [specification 0030 revision 2](../specs/2026-10-21-0030-public-monorepo.md).

Bring the public Core, Lumio SDK and optional LanceDB adapter into one uv
workspace so changes to their shared contract, CI and examples can be reviewed
atomically. Preserve standalone package boundaries and separate release channels:
Core keeps its own version, and the Lumio SDK/adapter keep their existing lockstep
family. The repository root coordinates development rather than distributing a
new umbrella package. Existing history is retained without rewriting published
commits. The private Lumio application and external Tau projects remain outside;
the already-present Ariadne Agent retains its separate development environment.

Keeping two public repositories preserves autonomy but makes each producer/consumer
change require source-pairing handoffs. A new public repository adds URL, tracker
and release-configuration migration without improving the package boundaries.
The selected existing repository avoids that extra move. A single version for
all packages would unnecessarily couple Core and optional adapter releases.

## Branding decision

Give both products equal visibility in the repository identity: the approved
canonical name is `legout/ariadne-lumio`, by renaming the already-selected existing
repository. Preserve `ariadne-data`, `lumio-wiki` and `lumio-lancedb` as public
package identities. Name availability and rename cutover remain unverified until
explicitly assigned. Retaining the old name was considered and not selected.

Renaming the SDK to `ariadne-knowledge` and its adapter to `ariadne-lancedb` would
suggest an Ariadne-specific subsystem, although the SDK remains a general-purpose
Knowledge Base foundation usable without Ariadne. It would also introduce public
packaging migration work unrelated to repository consolidation. This option is
therefore not recommended for the owner's stated independence goal. A new neutral
umbrella brand could represent both products, but choosing and migrating that
brand is a separate decision; no such name is assumed here.

Regardless of repository branding, the root documentation presents three complete
entry paths: Lumio alone, Ariadne alone, and explicit integrated use. Repository
colocation and workspace dependency resolution confer no integration/admission
authority. Installing one product must not require the other; installing both
must not activate their integration implicitly. These are observable obligations
in specification 0030, not promises inferred from package names.

The trade-off is shared developer dependency resolution and more path-sensitive
CI. Isolated built-wheel checks therefore remain essential: a successful workspace
import cannot demonstrate a valid standalone distribution. No license is inferred
from colocation. The public/private separation in Lumio ADR-0025 remains binding;
only its public-repository location receives the approved scoped amendment when
migration is executed.

This ADR records rationale, not execution, integration, publication, repository
archival or credential-configuration authority. Specification 0030 owns the
observable migration contract; its future plan owns task order and validation.
