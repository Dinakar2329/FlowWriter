from cryptography.fernet import Fernet
from flowwriter.vault import SecretVault, HISTORY_SECRET

class FakeKeyring:
    def __init__(self):
        self.values = {}
    def set_password(self, service, user, value):
        self.values[service,user] = value
    def get_password(self, service, user):
        return self.values.get((service,user))
    def delete_password(self, service, user):
        self.values.pop((service,user), None)

class FailingKeyring:
    def get_password(self, *args):
        raise RuntimeError("unavailable")
    def set_password(self, *args):
        raise RuntimeError("unavailable")


def test_secret_storage_and_history_cipher():
    fake = FakeKeyring()
    vault = SecretVault(fake)
    assert vault.put("provider-test", "abc")
    assert fake.get_password("FlowWriterStudio", "provider-test") == "abc"
    vault2 = SecretVault(fake)
    assert vault2.get("provider-test") == "abc"
    cipher = vault.history_cipher()
    secret = cipher.encrypt(b"private")
    assert vault2.history_cipher().decrypt(secret) == b"private"
    vault.remove("provider-test")
    assert vault2.get("provider-test") == ""


def test_broken_keyring_no_plaintext_key():
    vault = SecretVault(FailingKeyring())
    assert not vault.put("provider-a", "in-memory-key")
    assert vault.get("provider-a") == "in-memory-key"
    assert vault.history_cipher() is None


def test_environment_history_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FLOWWRITER_HISTORY_KEY", key)
    vault = SecretVault(FailingKeyring())
    assert vault.history_cipher().decrypt(vault.history_cipher().encrypt(b"test")) == b"test"


def test_missing_history_key_does_not_overwrite_existing_cipher(tmp_path):
    from flowwriter.storage import Store
    path = tmp_path / "history.db"
    first = SecretVault(FakeKeyring())
    cipher = first.history_cipher()
    store = Store(path, cipher)
    store.log_action("Refine", input_text="confidential", output_text="edited")
    store.close()
    second = SecretVault(FailingKeyring())
    assert second.history_cipher(path) is None
    assert second.get(HISTORY_SECRET) == ""
    locked = Store(path, None)
    assert locked.recent()[0]["input_text"].startswith("[Encrypted history unavailable")
    locked.close()
