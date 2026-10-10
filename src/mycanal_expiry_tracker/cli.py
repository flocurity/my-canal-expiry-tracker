"""Acquire and enrich a fresh playlist, or regenerate Excel from a report snapshot."""
import argparse
import math
from collections import Counter
from pathlib import Path
from xlsxwriter.exceptions import FileCreateError

from mycanal_hodor_core.diagnostics import debug_failure, redact
from mycanal_hodor_core.authentication import PassIdAuth, vault, profile_path
from mycanal_hodor_core.bootstrap import BootstrapError
from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.console import configure_console
from .acquisition import AcquisitionError, acquire_pages, parse_curl, read_curl
from .cache import load_snapshot, save_snapshot
from .canal_api import DEFAULT_DELAY, CanalClient, DetailError
from .excel import write_excel
from .playlist import parse_playlist
from .report import to_report_rows
from .tracker import process_items

log = get_logger(__name__)
ROOT = Path.cwd()


def nonnegative_delay(value: str) -> float:
    try:
        delay = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Delay must be a number') from exc
    if not math.isfinite(delay) or delay < 0:
        raise argparse.ArgumentTypeError('Delay must be finite and non-negative')
    return delay


def main(argv: list[str] | None = None, *, data_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--curl', action='store_true', help='Use explicit browser cURL authentication')
    parser.add_argument('--from-cache', action='store_true', help='Generate offline from the latest snapshot')
    parser.add_argument('--auth', choices=('set', 'delete'), help='Manage the shared passId in the secure keyring')
    parser.add_argument('--delay', type=nonnegative_delay,
                        help='Minimum HTTP request delay (default: 0.18s, plus jitter)')
    parser.add_argument('--data-dir', type=Path, default=data_dir or ROOT,
                        help='Directory containing cache and output (default: current directory)')
    args = parser.parse_args(argv)
    if args.from_cache and args.curl:
        parser.error('--from-cache cannot be combined with --curl')
    if args.auth and (args.curl or args.from_cache):
        parser.error('--auth is standalone')
    if args.delay is not None and (args.from_cache or args.auth):
        parser.error('--delay requires a network execution')
    workdir = args.data_dir.resolve()
    delay = DEFAULT_DELAY if args.delay is None else args.delay
    authentication = None
    diagnostic_secrets = ()
    persistence_secrets = ()
    try:
        if args.auth:
            vault(args.auth)
            log.info('credentials_updated', operation=args.auth)
            return 0
        if args.from_cache:
            rows = load_snapshot(workdir / 'cache')
        else:
            if args.curl:
                context = parse_curl(read_curl())
            else:
                pass_id = vault('get')
                if not pass_id:
                    raise BootstrapError('No passId registered; use --auth set or --curl')
                authentication = PassIdAuth(
                    pass_id, profile_file=profile_path('mycanal-expiry-tracker'))
                context = authentication.bootstrap()
            diagnostic_secrets = (tuple(authentication.secrets) if authentication is not None
                                  else (context.hodor_token, context.token_pass))
            with CanalClient(delay=delay, diagnostic_secrets=diagnostic_secrets) as client:
                client.authentication = authentication
                pages = acquire_pages(context, client, authentication)
                if authentication is not None:
                    diagnostic_secrets = tuple(authentication.secrets)
                items = parse_playlist(pages, secrets=diagnostic_secrets)
                results = process_items(items, client, secrets=diagnostic_secrets)
            rows = to_report_rows(results)
            diagnostic_secrets = (tuple(authentication.secrets) if authentication is not None
                                  else diagnostic_secrets)
            persistence_secrets = diagnostic_secrets + (context.token_pass,)
            if authentication is not None:
                persistence_secrets += (pass_id, authentication.headers['tokenPass'])
            snapshot = save_snapshot(rows, workdir / 'cache', secrets=persistence_secrets)
            log.info('snapshot_saved', path=str(snapshot), rows=len(rows))
        destination = workdir / 'output' / 'ma-liste-canal.xlsx'
        write_excel(rows, destination, secrets=persistence_secrets)
    except (AcquisitionError, BootstrapError, DetailError, FileCreateError, OSError, ValueError) as exc:
        if authentication is not None:
            diagnostic_secrets = tuple(authentication.secrets)
        log.error('execution_failed', reason=redact(str(exc), diagnostic_secrets))
        debug_failure(log, 'execution_failure_debug', exc, diagnostic_secrets)
        return 1
    except (EOFError, KeyboardInterrupt):
        log.error('execution_interrupted')
        return 1
    statuses = Counter(row.status for row in rows)
    log.info('export_completed', output=str(destination), rows=len(rows), statuses=dict(statuses))
    return 0


def run() -> int:
    configure_console()
    return main()


if __name__ == '__main__':
    raise SystemExit(run())
