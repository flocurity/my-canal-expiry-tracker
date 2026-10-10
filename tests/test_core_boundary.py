from unittest.mock import Mock
import json

import pytest
from structlog.testing import capture_logs
from mycanal_hodor_core.http import CanalClient as CoreClient
from mycanal_expiry_tracker.canal_api import CanalClient, DetailError


@pytest.mark.parametrize('status, payload, expected', [
    (403, {}, 'Erreur HTTP'),
    (200, {'detail': None}, 'Erreur parsing'),
])
def test_real_core_transport_errors_map_to_existing_report_status(item, status, payload, expected):
    with CanalClient(delay=0) as client:
        response = Mock(status_code=status, headers={})
        response.json.return_value = payload
        client.session.get = Mock(return_value=response)
        with pytest.raises(DetailError) as caught:
            client.fetch(item.detail_url, item.content_id)
        assert caught.value.status == expected
        response.close.assert_called_once()
        assert client._request.__func__ is CoreClient._request


def test_enrichment_diagnostics_hide_curl_credentials_without_headers(item):
    secrets = ('SYNTHETIC_HODOR', 'SYNTHETIC_PASS')
    response = Mock(status_code=400, headers={},
                    text=json.dumps({'message': 'visible marker ' + ' '.join(secrets)}))
    with capture_logs() as logs, CanalClient(delay=0, diagnostic_secrets=secrets) as client:
        client.session.get = Mock(return_value=response)
        with pytest.raises(DetailError):
            client.fetch(item.detail_url, item.content_id)
        assert client.session.get.call_args.kwargs.get('headers') is None
    assert 'visible marker' in str(logs)
    assert all(secret not in str(logs) for secret in secrets)
