"""A few discovered public endpoints; no hardcoded content identifiers."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from mycanal_expiry_tracker.canal_api import CanalClient, build_detail_url
from mycanal_expiry_tracker.expiration import extract_expiration
from mycanal_expiry_tracker.playlist import parse_playlist

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def playlist():
    if not list((ROOT / 'input').glob('*.json')):
        pytest.skip('No manually exported playlist JSON files available in input/')
    return parse_playlist([p.read_bytes() for p in sorted((ROOT / 'input').glob('*.json'))])


@pytest.fixture(scope='module')
def api():
    with CanalClient() as client:
        yield client


@pytest.fixture(scope='module')
def fetched():
    return {}


@pytest.mark.parametrize('case', ['movie', 'documentary', 'detailShow', 'detailSeason'])
def test_public_detail_contract(case, playlist, api, fetched):
    def matches(item):
        if case == 'movie':
            return item.subtitle.casefold().startswith('film ')
        if case == 'documentary':
            return item.subtitle.casefold().startswith(('doc.', 'documentaire'))
        return parse_qs(urlsplit(item.detail_url).query).get('detailType') == [case]

    candidates = [item for item in playlist if matches(item)]
    if not candidates:
        pytest.skip(f'No {case} entry in the current input playlists')
    item = candidates[0]
    request_url = build_detail_url(item.detail_url, item.supports_detail_v5)
    # Shared selections do not cause duplicate live requests.
    if request_url not in fetched:
        fetched[request_url] = api.fetch(request_url, item.content_id)
    payload = fetched[request_url]
    assert isinstance(payload['detail'], dict)
    expiration = extract_expiration(payload)
    info = payload['detail'].get('informations', {})
    if isinstance(info, dict):
        availability = info.get('contentAvailability', {})
        options = availability.get('availabilities', {}) if isinstance(availability, dict) else {}
        if isinstance(options, dict):
            timestamps = [value.get('availabilityEndDate') for value in options.values()
                          if isinstance(value, dict)]
            if any(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and 0 < value < 253402214400000 for value in timestamps):
                assert expiration is not None
