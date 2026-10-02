from unittest.mock import Mock

import pytest
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
