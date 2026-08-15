import hashlib, hmac
from app.services.security import find_secrets, verify_github_signature

def test_webhook_signature_validation():
    body=b'{"ok":true}'; sig="sha256="+hmac.new(b"test-secret",body,hashlib.sha256).hexdigest()
    assert verify_github_signature(body,sig,"test-secret")
    assert not verify_github_signature(body,"sha256=bad","test-secret")
def test_secret_detection():
    assert find_secrets("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx")
    assert not find_secrets("A perfectly ordinary portfolio description")
