import hashlib, hmac, re

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(?:password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]

def verify_github_signature(payload: bytes, signature: str | None, secret: str | None) -> bool:
    if not secret:
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def find_secrets(content: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(content)]
