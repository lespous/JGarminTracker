import certifi

from jgarmintracker import certs


def test_bundle_keeps_certifi_and_adds_system_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(certs, "windows_roots", lambda: ["-----BEGIN CERTIFICATE-----\nFAUX\n-----END CERTIFICATE-----\n"])
    path = certs.build_bundle(tmp_path / "ca.pem")
    text = path.read_text(encoding="ascii")
    assert text.startswith(open(certifi.where(), encoding="ascii").read()[:200]) and "FAUX" in text


def test_nothing_to_add_means_no_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(certs, "windows_roots", lambda: [])
    assert certs.build_bundle(tmp_path / "ca.pem") is None


def test_existing_setting_or_opt_out_is_respected(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "deja-defini.pem")
    assert certs.use_system_certificates() is None
    monkeypatch.delenv("SSL_CERT_FILE")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.setenv("JGARMIN_SYSTEM_CERTS", "0")
    assert certs.use_system_certificates() is None
