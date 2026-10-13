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


def _write(path, payload):
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


GOOD = {"id": "a" * 32, "name": "Omen", "url": "http://127.0.0.1:7866"}


def test_recovering_load_of_missing_file_is_empty(tmp_path):
    result = ProfileStore(tmp_path / "connections.json").load_recovering()
    assert result.profiles == [] and result.warning is None and result.backup is None


@pytest.mark.parametrize("text", [
    "{", "[]", '{"version": 2, "profiles": []}', '{"version": 1}', '{"version": 1, "profiles": {}}',
])
def test_unusable_file_is_backed_up_and_ignored(tmp_path, text):
    path = tmp_path / "connections.json"
    _write(path, text)
    store = ProfileStore(path)
    with pytest.raises(ValueError):
        store.load()
    result = store.load_recovering()
    assert result.profiles == []
    assert result.warning and "could not be read" in result.warning
    assert result.backup is not None and result.backup.read_text(encoding="utf-8") == text
    assert path.read_text(encoding="utf-8") == text  # Never destroyed by loading.


def test_partially_damaged_file_keeps_good_profiles(tmp_path):
    path = tmp_path / "connections.json"
    _write(path, {"version": 1, "profiles": [
        GOOD, {**GOOD, "id": "b" * 32, "url": "ftp://bad"}, "not an object", {"id": "c"},
    ]})
    result = ProfileStore(path).load_recovering()
    assert [p.name for p in result.profiles] == ["Omen"]
    assert result.warning and "3 saved connection(s)" in result.warning
    assert result.backup is not None and result.backup.exists()


def test_unknown_profile_fields_are_ignored_without_warning(tmp_path):
    path = tmp_path / "connections.json"
    _write(path, {"version": 1, "profiles": [{**GOOD, "added_by_newer_studio": 1}]})
    result = ProfileStore(path).load_recovering()
    assert len(result.profiles) == 1 and result.warning is None
    assert len(ProfileStore(path).load()) == 1


def test_saved_file_has_no_doubled_line_endings(tmp_path):
    path = tmp_path / "connections.json"
    ProfileStore(path).save([ConnectionProfile.create("One", "http://localhost:7866")])
    assert b"\r\r" not in path.read_bytes()
    assert not (tmp_path / "connections.json.tmp").exists()
