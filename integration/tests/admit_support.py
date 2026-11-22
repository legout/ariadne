"""Test-only driver for the library admission calls, keeping the flag vocabulary the
suites already use. The shipped surface is ``ariadne approve``; this module is not
packaged and no agent surface imports it."""

from __future__ import annotations

import argparse
import json
import sys
from getpass import getuser

from ariadne import admission


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def admit_cli(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="admit")
    parser.add_argument("--project", default=".")
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reviewed-digest", required=True)
    parser.add_argument("--confirm-mapping", action="append", default=[], dest="confirm_mappings")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--by", default=None)
    parser.add_argument("--context-destination")
    parser.add_argument("--context-storage-profile", default=None)
    parser.add_argument("--context-private-profile", default=None)
    parser.add_argument("--context-expected-current", default="none")
    parser.add_argument("--visibility", action="append", default=None)
    parser.add_argument("--overall-digest")
    try:
        args = parser.parse_args(argv)
        composite = (
            admission.overall_review(
                args.project,
                args.proposal,
                args.revision,
                args.reviewed_digest,
                destination=args.context_destination,
                expected_current=args.context_expected_current,
                scope=args.visibility or ["public"],
                confirm_mappings=args.confirm_mappings,
                storage_profile=args.context_storage_profile,
                private_profile=args.context_private_profile,
            )
            if args.context_destination
            else None
        )
        if args.confirm:
            result = admission.admit_revision(
                args.project,
                args.proposal,
                args.revision,
                args.reviewed_digest,
                confirmed_by=args.by or f"human:{getuser()}",
                confirm_mappings=args.confirm_mappings,
                overall_preview=composite,
                confirmed_overall_digest=args.overall_digest,
                private_profile=args.context_private_profile,
            )
        else:
            result = (
                composite
                if composite is not None
                else admission.admission_review(
                    args.project,
                    args.proposal,
                    args.revision,
                    args.reviewed_digest,
                    confirm_mappings=args.confirm_mappings,
                )
            )
    except Exception as exc:
        print(
            json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0
