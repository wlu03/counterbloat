import pytest

from backend.ingestion.fetch import BlockedDestination, validate_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://localhost:8000/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "file:///etc/passwd",
    "ftp://example.com/file", "gopher://example.com/",
])
def test_private_and_non_http_destinations_are_blocked(url):
    with pytest.raises(BlockedDestination):
        validate_url(url)
