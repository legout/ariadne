---
status: proposed
---

# ADR-0027: Public Ariadne–Lumio monorepo with independent packages

The owner selected existing `legout/ariadne` as the target on 2026-10-21.
The complete decision is proposed pending approval of
[specification 0030 revision 1](../specs/2026-10-21-0030-public-monorepo.md).

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

The trade-off is shared developer dependency resolution and more path-sensitive
CI. Isolated built-wheel checks therefore remain essential: a successful workspace
import cannot demonstrate a valid standalone distribution. No license is inferred
from colocation. The public/private separation in Lumio ADR-0025 remains binding;
only its public-repository location would receive a scoped amendment on approval.

This ADR records rationale, not execution, integration, publication, repository
archival or credential-configuration authority. Specification 0030 owns the
observable migration contract; its future plan owns task order and validation.
