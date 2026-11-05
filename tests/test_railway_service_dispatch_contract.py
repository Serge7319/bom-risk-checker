from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "scripts" / "railway_start.sh"


def test_migration_api_services_dispatch_to_api_startup():
    source = START.read_text(encoding="utf-8")

    assert '"${service_name}" == "cadivor-next-api"' in source
    assert '"${service_name}" == "cadivor-next-api-prod"' in source
    assert 'exec bash apps/api/start.sh' in source
    assert "start_migration_api.sh" not in source


def test_customer_streamlit_service_keeps_streamlit_startup():
    source = START.read_text(encoding="utf-8")

    assert 'exec python scripts/cadivor_streamlit_boot.py' in source
    assert '"${service_name}" == "bom-risk-checker"' not in source
