from apps.api.sandbox_auth import _FileAuthStore, _PostgresAuthStore


def test_auth_stores_advertise_their_storage_backend(tmp_path):
    file_store = _FileAuthStore(tmp_path / "auth.json")
    postgres_store = _PostgresAuthStore("postgresql://localhost/cadivor_test")

    assert file_store.backend == "file"
    assert postgres_store.backend == "postgres"
