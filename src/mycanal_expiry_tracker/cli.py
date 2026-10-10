"""Acquire a fresh authenticated playlist and export its Excel report."""

import argparse
import math
from collections import Counter
from pathlib import Path

from mycanal_hodor_core.diagnostics import debug_failure, redact
from mycanal_hodor_core.authentication import (
    PassIdAuth, vault, profile_path, remembered_profile,
)
from mycanal_hodor_core.bootstrap import BootstrapError
from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.console import configure_console
from mycanal_expiry_tracker.acquisition import AcquisitionError, acquire_pages, parse_curl, publish_pages, read_curl
from mycanal_expiry_tracker.cache import DetailCache
from mycanal_expiry_tracker.canal_api import DEFAULT_DELAY, CanalClient, DetailError
from mycanal_expiry_tracker.excel import write_excel
from mycanal_expiry_tracker.playlist import PlaylistError, load_playlist
from mycanal_expiry_tracker.tracker import process_items

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
    parser.add_argument('--curl', action='store_true', help='Use an explicit browser cURL authentication')
    parser.add_argument('--from-cache', action='store_true', help='Generate strictly offline from local data')
    parser.add_argument('--auth', choices=('set', 'delete'), help='Manage the shared passId in the secure keyring')
    parser.add_argument('--refresh', action='store_true', help='Ignore cached details')
    parser.add_argument('--delay', type=nonnegative_delay, default=DEFAULT_DELAY,
                        help='Minimum delay between requests in seconds (default: 0.18)' +
                        ' with up to 0.15s jitter')
    parser.add_argument("--data-dir", type=Path, default=data_dir or ROOT,
                        help="Directory containing input, cache and output (default: current directory)")
    args = parser.parse_args(argv)
    workdir = args.data_dir.resolve()
    if args.from_cache and (args.curl or args.refresh):
        parser.error('--from-cache cannot be combined with --curl or --refresh')
    if args.auth and (args.curl or args.from_cache or args.refresh):
        parser.error('--auth is standalone')
    authentication = None
    secrets = ()
    try:
        if args.auth:
            vault(args.auth)
            log.info('credentials_updated', operation=args.auth)
            return 0
        if not args.from_cache:
            if args.curl:
                context = parse_curl(read_curl())
            else:
                pass_id = vault('get')
                if not pass_id:
                    raise BootstrapError('No passId registered; use --auth set or --curl')
                authentication = PassIdAuth(
                    pass_id, profile_file=profile_path('mycanal-expiry-tracker'))
                context = authentication.bootstrap()
            secrets = (tuple(authentication.secrets) if authentication is not None
                       else (context.hodor_token, context.token_pass, context.profile_id))
            with CanalClient(delay=args.delay) as client:
                client.authentication = authentication
                pages = acquire_pages(context, client, authentication)
            input_directory = workdir / 'input'
            previous_profile = remembered_profile(input_directory / '.acquisition-profile')
            changed_profile = previous_profile != context.profile_id
            paths = publish_pages(
                pages, input_directory, profile_id=context.profile_id,
                cache_directory=workdir / 'cache' if changed_profile else None)
            log.info('playlist_acquired', pages=len(paths), profile_changed=changed_profile)
    except (AcquisitionError, BootstrapError, DetailError) as exc:
        if authentication is not None:
            secrets = tuple(authentication.secrets)
        log.error('acquisition_failed', reason=redact(str(exc), secrets))
        debug_failure(log, 'acquisition_failure_debug', exc, secrets)
        return 1
    except (OSError, EOFError, KeyboardInterrupt):
        log.error('acquisition_failed', reason='Acquisition interrupted or input/output unavailable')
        return 1
    try:
        # Validate every file before opening the client or touching the output.
        items = load_playlist(workdir / 'input')
        cache = DetailCache(workdir / 'cache' / 'details.json')
        if args.from_cache:
            results = process_items(items, None, cache, offline=True)
        else:
            # A normal run builds a fresh snapshot, never reusing old enrichment
            # or personalized resume fallbacks from a previous acquisition.
            cache.entries.clear()
            cache.dirty = True
            with CanalClient(delay=args.delay) as client:
                client.authentication = authentication
                results = process_items(items, client, cache, refresh=True)
        destination = workdir / 'output' / 'ma-liste-canal.xlsx'
        write_excel(results, destination)
    except (PlaylistError, OSError, ValueError) as exc:
        log.error('export_failed', reason=redact(str(exc), secrets))
        debug_failure(log, 'export_failure_debug', exc, secrets)
        return 1
    statuses = Counter(result.status for result in results)
    log.info('export_completed', output=str(destination), items=len(results),
             statuses=dict(statuses))
    return 0


def run() -> int:
    configure_console()
    return main()


if __name__ == '__main__':
    raise SystemExit(run())
