"""Acquire raw playlist inputs or export their Excel availability report."""

import argparse
import math
from collections import Counter
from pathlib import Path

from log import get_logger
from src.acquisition import AcquisitionError, acquire_pages, parse_curl, publish_pages, read_curl
from src.cache import DetailCache
from src.canal_api import DEFAULT_DELAY, CanalClient, DetailError
from src.excel import write_excel
from src.playlist import PlaylistError, load_playlist
from src.tracker import process_items

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parent


def nonnegative_delay(value: str) -> float:
    try:
        delay = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Delay must be a number') from exc
    if not math.isfinite(delay) or delay < 0:
        raise argparse.ArgumentTypeError('Delay must be finite and non-negative')
    return delay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--getinfo', action='store_true', help='Acquire raw playlist inputs')
    parser.add_argument('--refresh', action='store_true', help='Ignore cached details')
    parser.add_argument('--delay', type=nonnegative_delay, default=DEFAULT_DELAY,
                        help='Minimum delay between requests in seconds (default: 0.18)' +
                        ' with up to 0.15s jitter')
    args = parser.parse_args(argv)
    if args.getinfo:
        try:
            context = parse_curl(read_curl())
            with CanalClient(delay=args.delay) as client:
                pages = acquire_pages(context, client)
            paths = publish_pages(pages, ROOT / 'input')
        except (AcquisitionError, DetailError) as exc:
            log.error('acquisition_failed', reason=str(exc))
            return 1
        except (OSError, EOFError, KeyboardInterrupt):
            log.error('acquisition_failed', reason='Acquisition interrupted or input/output unavailable')
            return 1
        log.info('playlist_acquired', pages=len(paths),
                 files=[str(path.relative_to(ROOT)) for path in paths])
        return 0
    try:
        # Validate every file before opening the client or touching the output.
        items = load_playlist(ROOT / 'input')
        cache = DetailCache(ROOT / 'cache' / 'details.json')
        with CanalClient(delay=args.delay) as client:
            results = process_items(items, client, cache, refresh=args.refresh)
        destination = ROOT / 'output' / 'ma-liste-canal.xlsx'
        write_excel(results, destination)
    except (PlaylistError, OSError, ValueError) as exc:
        log.error('export_failed', reason=str(exc))
        return 1
    statuses = Counter(result.status for result in results)
    log.info('export_completed', output=str(destination), items=len(results),
             statuses=dict(statuses))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
