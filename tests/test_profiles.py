import json
import pytest

from morphorum_studio.backend.profiles import ConnectionProfile, ProfileStore
from morphorum_studio.backend.credentials import CredentialStore


def test_profiles_round_trip_without_secrets(tmp_path):
    store = ProfileStore(tmp_path / "connections.json")
    profile = ConnectionProfile.create("My Omen", "http://127.0.0.1:7866/")
    profile.instance_id = "a" * 32
    store.save([profile])
    assert store.load() == [profile]
    raw = (tmp_path / "connections.json").read_text()
    assert "token" not in raw and "password" not in raw
    assert json.loads(raw)["version"] == 1


def test_invalid_profile_name():
    with pytest.raises(ValueError):
        ConnectionProfile.create(" ", "http://localhost:7866")


class FakeVault:
    def __init__(self):
        self.secrets = {}

    def get_password(self, service, key):
        return self.secrets.get((service, key))

    def set_password(self, service, key, secret):
        self.secrets[(service, key)] = secret

    def delete_password(self, service, key):
        del self.secrets[(service, key)]


def test_credential_store_round_trip():
    vault = FakeVault()
    store = CredentialStore(vault)
    store.set("profile-one", "example-test-token")
    assert store.get("profile-one") == "example-test-token"
    store.delete("profile-one")
    assert store.get("profile-one") is None
