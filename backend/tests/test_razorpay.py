import hashlib
import hmac
import json

from test_api import client, login  # noqa: F401  (pytest fixture + helper)

KEY_ID, SECRET, HOOK = "rzp_test_ABC123", "test_secret_xyz", "hook_secret_123"


def sign(secret, msg: bytes):
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def setup_gateway(monkeypatch, paid_amount=None):
    """Turn on Razorpay with fake keys and a fake Razorpay API."""
    import app.billing as billing
    from app import config

    monkeypatch.setattr(config, "RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setattr(config, "RAZORPAY_KEY_SECRET", SECRET)
    monkeypatch.setattr(config, "RAZORPAY_WEBHOOK_SECRET", HOOK)
    orders = {}

    def fake_rzp(method, path, **kw):
        if method == "POST" and path == "/orders":
            oid = f"order_{len(orders) + 1:04d}"
            orders[oid] = kw["json"]
            return {"id": oid, "amount": kw["json"]["amount"], "currency": "INR", "status": "created"}
        if method == "GET" and path.startswith("/payments/"):
            oid = list(orders)[-1]  # the payment belongs to the most recent order
            return {"id": path.rsplit("/", 1)[1], "order_id": oid, "method": "upi",
                    "amount": paid_amount if paid_amount is not None else orders[oid]["amount"], "status": "captured"}
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(billing, "_rzp", fake_rzp)
    return orders


def register_unpaid(client):
    from app.college_db import get_directory
    import sqlite3, os
    reg = {r[0] for r in sqlite3.connect(os.environ["APP_DB_PATH"]).execute("SELECT username FROM users")}
    s = next(x for x in get_directory().all_students() if not x.fee_paid and x.student_id not in reg)
    r = client.post("/api/auth/register", json={"student_id": s.student_id, "name": s.name, "password": "secret1"})
    return s, {"Authorization": f"Bearer {r.json()['token']}"}


def test_checkout_verify_and_webhook(client, monkeypatch):
    orders = setup_gateway(monkeypatch)
    s, me = register_unpaid(client)
    admin = login(client, "admin", "admin123")

    fee = client.get("/api/me/fee", headers=me).json()
    assert fee["gateway"] == "razorpay" and fee["test_mode"] is True
    assert client.post("/api/me/fee/pay", json={"method": "upi"}, headers=me).status_code == 400  # demo disabled

    order = client.post("/api/me/fee/order", headers=me).json()
    assert order["key_id"] == KEY_ID and order["amount"] == fee["amount"] * 100
    assert orders[order["order_id"]]["notes"]["student_id"] == s.student_id

    # forged signature is rejected and the fee stays unpaid
    bad = client.post("/api/me/fee/verify", headers=me, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_FAKE1", "razorpay_signature": "0" * 64})
    assert bad.status_code == 400
    assert client.get("/api/me/fee", headers=me).json()["paid"] is False

    # a fresh order with a genuine signature succeeds
    order = client.post("/api/me/fee/order", headers=me).json()
    sig = sign(SECRET, f"{order['order_id']}|pay_REAL1".encode())
    ok = client.post("/api/me/fee/verify", headers=me, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_REAL1", "razorpay_signature": sig})
    assert ok.status_code == 200, ok.text
    assert ok.json()["receipt"]["reference"] == "pay_REAL1"
    assert client.get("/api/me/fee", headers=me).json()["paid"] is True
    assert client.post("/api/me/fee/order", headers=me).status_code == 409  # can't pay twice

    # the webhook for the same payment doesn't double count
    event = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_REAL1", "order_id": order["order_id"], "amount": order["amount"], "method": "upi"}}}}).encode()
    assert client.post("/api/payments/razorpay/webhook", content=event,
                       headers={"X-Razorpay-Signature": "bad"}).status_code == 400
    assert client.post("/api/payments/razorpay/webhook", content=event,
                       headers={"X-Razorpay-Signature": sign(HOOK, event)}).json()["ok"]
    rep = client.get("/api/admin/payments", headers=admin).json()
    assert rep["gateway"] == "razorpay" and rep["online_count"] == 1
    assert [p["reference"] for p in rep["recent"]] == ["pay_REAL1"]  # failed/abandoned orders aren't listed


def test_webhook_alone_marks_paid_when_tab_closed(client, monkeypatch):
    setup_gateway(monkeypatch)
    s, me = register_unpaid(client)
    order = client.post("/api/me/fee/order", headers=me).json()
    event = json.dumps({"event": "order.paid", "payload": {"payment": {"entity": {
        "id": "pay_WH1", "order_id": order["order_id"], "amount": order["amount"], "method": "card"}}}}).encode()
    assert client.post("/api/payments/razorpay/webhook", content=event,
                       headers={"X-Razorpay-Signature": sign(HOOK, event)}).json()["ok"]
    fee = client.get("/api/me/fee", headers=me).json()
    assert fee["paid"] is True and fee["receipt"]["method"] == "card"


def test_amount_mismatch_is_rejected(client, monkeypatch):
    setup_gateway(monkeypatch, paid_amount=100)  # gateway reports ₹1 paid
    s, me = register_unpaid(client)
    order = client.post("/api/me/fee/order", headers=me).json()
    sig = sign(SECRET, f"{order['order_id']}|pay_X".encode())
    r = client.post("/api/me/fee/verify", headers=me, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_X", "razorpay_signature": sig})
    assert r.status_code == 400
    assert client.get("/api/me/fee", headers=me).json()["paid"] is False
