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


def test_request_goes_to_the_checked_address(monkeypatch):
    """The second DNS answer is private. The fetch must not connect to it."""
    import socket

    import httpx

    from backend.ingestion import fetch as module

    answers = iter(["93.184.216.34", "127.0.0.1"])
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(2, 1, 6, "", (next(answers), 0))])
    seen = {}

    def handler(request):
        seen["host"], seen["header"] = request.url.host, request.headers["host"]
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>ok</p>")

    real = httpx.Client
    monkeypatch.setattr(module.httpx, "Client",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler)))
    content, media_type, _ = module.fetch("http://rebind.test/page")
    assert content == b"<p>ok</p>" and media_type == "text/html"
    assert seen == {"host": "93.184.216.34", "header": "rebind.test"}


def test_transport_and_parse_failures_are_fetch_errors(monkeypatch, store):
    import httpx

    from backend.ingestion import fetch as module
    from backend.ingestion.snapshot import admit

    def refuse(request):
        raise httpx.ConnectError("refused")

    real = httpx.Client
    monkeypatch.setattr(module, "validate_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(module.httpx, "Client",
                        lambda **kwargs: real(transport=httpx.MockTransport(refuse)))
    with pytest.raises(module.FetchError):
        module.fetch("http://example.com/")
    with pytest.raises(module.FetchError):
        admit(store, b"<!-- app shell -->", "text/html")


def test_user_agent_comes_from_the_environment(monkeypatch):
    import httpx

    from backend.ingestion import fetch as module

    seen = {}

    def handler(request):
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    real = httpx.Client
    monkeypatch.setenv("FETCH_USER_AGENT", "Example Org contact@example.org")
    monkeypatch.setattr(module, "validate_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(module.httpx, "Client",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler)))
    module.fetch("http://example.com/")
    assert seen["agent"] == "Example Org contact@example.org"
