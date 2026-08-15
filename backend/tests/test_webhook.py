import hashlib, hmac, json
from fastapi.testclient import TestClient
from app.main import app
from app.models import Repository

def test_duplicate_webhook_is_idempotent(db):
    db.add(Repository(owner="octo",name="demo"));db.commit()
    payload={"repository":{"owner":{"login":"octo"},"name":"demo"},"pusher":{"name":"human"},"commits":[]}
    raw=json.dumps(payload).encode(); sig="sha256="+hmac.new(b"test-secret",raw,hashlib.sha256).hexdigest()
    c=TestClient(app); headers={"X-GitHub-Event":"push","X-GitHub-Delivery":"event-1","X-Hub-Signature-256":sig}
    assert c.post("/webhooks/github",content=raw,headers=headers).status_code==202
    assert c.post("/webhooks/github",content=raw,headers=headers).json()["status"]=="duplicate"
