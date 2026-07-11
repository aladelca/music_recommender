from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Protocol

from dotenv import load_dotenv

from music_recommender.auth.beta_access import BetaAccessService, safe_account_payload
from music_recommender.config import load_settings
from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings
from music_recommender.storage.postgres_repositories import PostgresRepositories
from music_recommender.storage.protocols import (
    ApprovedUserLimitError,
    EvaluationCompletenessRecord,
)


class EvaluationCompletenessReader(Protocol):
    def completeness(self) -> EvaluationCompletenessRecord: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administer the five-user beta allowlist.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("pending", help="List accounts awaiting internal approval.")

    approve = subparsers.add_parser("approve", help="Approve one Spotify account.")
    approve.add_argument("account_id")

    revoke = subparsers.add_parser("revoke", help="Revoke one Spotify account and its sessions.")
    revoke.add_argument("account_id")

    status = subparsers.add_parser("status", help="Show beta capacity or one account status.")
    status.add_argument("account_id", nargs="?", default=None)
    subparsers.add_parser(
        "evaluations",
        help="Show aggregate beta evaluation completion without account identifiers.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    service: BetaAccessService | None = None,
    evaluation_reader: EvaluationCompletenessReader | None = None,
) -> int:
    load_dotenv(".env")
    args = build_parser().parse_args(argv)
    database: PostgresDatabase | None = None
    if service is None:
        settings = load_settings()
        database = PostgresDatabase(PostgresPoolSettings.from_settings(settings))
        repositories = PostgresRepositories(database)
        service = BetaAccessService(repository=repositories.beta_access)
        evaluation_reader = repositories.session_evaluations
    try:
        payload = _execute(args, service, evaluation_reader=evaluation_reader)
    except (ApprovedUserLimitError, LookupError, ValueError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        if database is not None:
            database.close()
    print(json.dumps(payload, sort_keys=True))
    return 0


def _execute(
    args: argparse.Namespace,
    service: BetaAccessService,
    *,
    evaluation_reader: EvaluationCompletenessReader | None,
) -> dict[str, object]:
    command = str(args.command)
    if command == "pending":
        accounts = [safe_account_payload(account) for account in service.pending()]
        return {"accounts": accounts, "count": len(accounts)}
    if command == "approve":
        return safe_account_payload(service.approve(str(args.account_id)))
    if command == "revoke":
        return safe_account_payload(service.revoke(str(args.account_id)))
    if command == "status":
        return service.status(args.account_id)
    if command == "evaluations":
        if evaluation_reader is None:
            raise ValueError("Evaluation completeness repository is not configured.")
        return asdict(evaluation_reader.completeness())
    raise RuntimeError("Unsupported beta admin command.")


if __name__ == "__main__":
    sys.exit(main())
