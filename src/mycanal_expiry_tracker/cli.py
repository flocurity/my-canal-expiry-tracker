"""Acquire raw playlist inputs or export their Excel availability report."""

import argparse
import math
from collections import Counter
from pathlib import Path

from mycanal_hodor_core.diagnostics import debug_failure
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
    parser.add_argument('--getinfo', action='store_true', help='Acquire raw playlist inputs')
    parser.add_argument('--refresh', action='store_true', help='Ignore cached details')
    parser.add_argument('--delay', type=nonnegative_delay, default=DEFAULT_DELAY,
                        help='Minimum delay between requests in seconds (default: 0.18)' +
                        ' with up to 0.15s jitter')
    parser.add_argument("--data-dir", type=Path, default=data_dir or ROOT,
                        help="Directory containing input, cache and output (default: current directory)")
    args = parser.parse_args(argv)
    workdir = args.data_dir.resolve()
    if args.getinfo:
        try:
            context = parse_curl(read_curl())
            with CanalClient(delay=args.delay) as client:
                pages = acquire_pages(context, client)
            paths = publish_pages(pages, workdir / 'input')
        except (AcquisitionError, DetailError) as exc:
            log.error('acquisition_failed', reason=str(exc))
            request_context = locals().get('context')
            secrets = ((request_context.hodor_token, request_context.token_pass, request_context.profile_id)
                       if request_context is not None else ())
            debug_failure(log, 'acquisition_failure_debug', exc, secrets)
            return 1
        except (OSError, EOFError, KeyboardInterrupt):
            log.error('acquisition_failed', reason='Acquisition interrupted or input/output unavailable')
            return 1
        log.info('playlist_acquired', pages=len(paths),
                 files=[str(path.relative_to(workdir)) for path in paths])
        return 0
    try:
        # Validate every file before opening the client or touching the output.
        items = load_playlist(workdir / 'input')
        cache = DetailCache(workdir / 'cache' / 'details.json')
        with CanalClient(delay=args.delay) as client:
            results = process_items(items, client, cache, refresh=args.refresh)
        destination = workdir / 'output' / 'ma-liste-canal.xlsx'
        write_excel(results, destination)
    except (PlaylistError, OSError, ValueError) as exc:
        log.error('export_failed', reason=str(exc))
        debug_failure(log, 'export_failure_debug', exc)
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
