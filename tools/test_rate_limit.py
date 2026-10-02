"""Manually observe a few public detail responses; stop immediately on HTTP 429."""

import argparse
import time

import requests

from mycanal_hodor_core.logging import get_logger
from mycanal_hodor_core.console import configure_console
from mycanal_expiry_tracker.cli import nonnegative_delay
from mycanal_expiry_tracker.canal_api import TIMEOUT_SECONDS, USER_AGENT, DetailError, validate_detail_url

log = get_logger(__name__)
HEADERS = ('Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset',
           'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset')


def request_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 20:
        raise argparse.ArgumentTypeError('Count must be between 1 and 20')
    return count


def observation_delay(value: str) -> float:
    delay = nonnegative_delay(value)
    if delay < 1:
        raise argparse.ArgumentTypeError('Observation delay must be at least 1 second')
    return delay


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--count', type=request_count, default=3)
    parser.add_argument('--delay', type=observation_delay, default=1.0)
    args = parser.parse_args(argv)
    try:
        validate_detail_url(args.url)
    except DetailError as exc:
        parser.error(str(exc))
    with requests.Session() as session:
        session.headers['User-Agent'] = USER_AGENT
        session.headers['Accept-Encoding'] = 'deflate, gzip'
        for index in range(args.count):
            if index:
                time.sleep(args.delay)
            started = time.monotonic()
            try:
                response = session.get(args.url, timeout=TIMEOUT_SECONDS, allow_redirects=False)
            except requests.RequestException as exc:
                log.error('api_observation_failed', reason=type(exc).__name__)
                return 1
            with response:
                log.info('api_observation', request=index + 1, status_code=response.status_code,
                         elapsed_seconds=round(time.monotonic() - started, 3),
                         headers={name: response.headers.get(name) for name in HEADERS})
                # An error is already enough evidence; do not repeat rejected requests.
                if response.status_code >= 400:
                    log.warning('api_observation_stopped', status_code=response.status_code)
                    break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
