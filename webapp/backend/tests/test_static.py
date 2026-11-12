import re
from pathlib import Path

from fastapi.testclient import TestClient

from erw.main import create_app


def test_spa_serving_when_dist_exists(client: TestClient):
    """Test that GET / serves the SPA index.html when dist exists."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert '<div id="root">' in res.text
    assert "Early Risk Web" in res.text


def test_spa_fallback_routes(client: TestClient):
    """Test that frontend SPA routes fall back to index.html."""
    for path in ["/dashboard", "/login", "/admin", "/issues/DEMO-101"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert '<div id="root">' in res.text


def test_assets_serving(client: TestClient):
    """Test that static assets in /assets are served with 200."""
    index_res = client.get("/")
    assert index_res.status_code == 200

    # Extract asset paths from index.html (e.g. /assets/index-*.js)
    asset_matches = re.findall(r'src="(/assets/[^"]+)"', index_res.text)
    assert len(asset_matches) > 0, "Expected at least one js asset in index.html"

    for asset_path in asset_matches:
        asset_res = client.get(asset_path)
        assert asset_res.status_code == 200


def test_api_routes_not_swallowed(client: TestClient):
    """Test that /healthz and /api/* routes are not swallowed by SPA fallback."""
    # Health endpoint returns JSON, not index.html
    health_res = client.get("/healthz")
    assert health_res.status_code == 200
    assert health_res.headers.get("content-type", "").startswith("application/json")
    assert health_res.json().get("status") == "ok"

    # Unknown /api route returns 404 JSON, not SPA index.html
    api_res = client.get("/api/unknown_endpoint")
    assert api_res.status_code == 404
    assert '<div id="root">' not in api_res.text

    # Unknown /webhooks route returns 404 JSON, not SPA index.html
    webhook_res = client.get("/webhooks/unknown")
    assert webhook_res.status_code == 404
    assert '<div id="root">' not in webhook_res.text


def test_custom_frontend_dist(tmp_path: Path, settings, engine):
    """Test explicit frontend_dist argument with mock assets and index.html."""
    dist_dir = tmp_path / "mock_dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)

    index_file = dist_dir / "index.html"
    index_file.write_text("<!doctype html><html><body><h1>Mock SPA</h1></body></html>", encoding="utf-8")

    dummy_js = assets_dir / "bundle.js"
    dummy_js.write_text("console.log('mock');", encoding="utf-8")

    app = create_app(
        settings,
        engine=engine,
        catch_up_on_startup=False,
        start_scheduler_on_startup=False,
        frontend_dist=dist_dir,
    )

    with TestClient(app) as test_client:
        # Root route serves index.html
        res = test_client.get("/")
        assert res.status_code == 200
        assert "<h1>Mock SPA</h1>" in res.text

        # SPA fallback route serves index.html
        res = test_client.get("/reports/weekly")
        assert res.status_code == 200
        assert "<h1>Mock SPA</h1>" in res.text

        # Asset route serves static asset
        res = test_client.get("/assets/bundle.js")
        assert res.status_code == 200
        assert "console.log('mock');" in res.text

        # API route still returns 404, not index.html
        res = test_client.get("/api/not_found")
        assert res.status_code == 404
        assert "<h1>Mock SPA</h1>" not in res.text


def test_when_dist_does_not_exist(tmp_path: Path, settings, engine):
    """Test that app functions normally with 404 for root when frontend_dist does not exist."""
    non_existent = tmp_path / "does_not_exist"
    app = create_app(
        settings,
        engine=engine,
        catch_up_on_startup=False,
        start_scheduler_on_startup=False,
        frontend_dist=non_existent,
    )

    with TestClient(app) as test_client:
        res = test_client.get("/")
        assert res.status_code == 404

        res = test_client.get("/healthz")
        assert res.status_code == 200
        assert res.json().get("status") == "ok"
