from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_CLIENT = ROOT / "apps" / "web" / "src" / "lib" / "api.ts"
WEB_DOCKERFILE = ROOT / "apps" / "web" / "Dockerfile"


def test_web_build_has_no_silent_sandbox_api_fallback():
    api_source = API_CLIENT.read_text(encoding="utf-8")
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")

    assert "cadivor-next-api-sandbox.up.railway.app" not in api_source
    assert "DEFAULT_API_BASE" not in api_source
    assert "if (!API_BASE)" in api_source
    assert "ARG NEXT_PUBLIC_API_BASE=" not in dockerfile


def test_web_client_rejects_localhost_api_endpoint():
    api_source = API_CLIENT.read_text(encoding="utf-8")

    assert "localhost|127\\.0\\.0\\.1" in api_source
