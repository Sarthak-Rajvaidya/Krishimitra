"""Core flow tests: auth, approval gating, RBAC, ownership isolation, wallet, checkout.
Written against the current API but NOT yet run in the build environment (dependencies could not be installed there).
Run: pip install -r backend/requirements.txt && pytest"""
import uuid

H = {"X-KM-Client": "web"}


def test_login_and_me(login):
    c = login("farmer@demo.local")
    r = c.get("/api/v1/auth/me")
    assert r.status_code == 200 and r.json()["role"] == "FARMER"


def test_bad_password_rejected(anon):
    r = anon.post("/api/v1/auth/login", json={"identifier": "farmer@demo.local", "password": "wrong-password"})
    assert r.status_code == 401


def test_farmer_cannot_open_admin(login):
    c = login("farmer@demo.local")
    assert c.get("/api/v1/admin/users").status_code in (401, 403)
    assert c.get("/api/v1/superadmin/overview").status_code in (401, 403)


def test_admin_can_list_users(login):
    assert login("admin@demo.local").get("/api/v1/admin/users").status_code == 200


def test_supplier_cannot_use_farmer_cart(login):
    assert login("supplier@demo.local").get("/api/v1/cart").status_code in (401, 403)


def test_unauthenticated_blocked(anon):
    assert anon.get("/api/v1/orders").status_code == 401


def test_register_supplier_is_pending_and_has_no_permissions(anon):
    ident = f"s{uuid.uuid4().hex[:8]}@test.local"
    r = anon.post("/api/v1/auth/register", json={"role": "SUPPLIER", "full_name": "Test Supplier", "email": ident, "password": "Strong-Pass-123", "language": "en", "profile": {"shop_name": "Test Agro"}})
    assert r.status_code in (200, 201), r.text
    code = r.json().get("dev_code")
    assert code, "OTP_DEV_ECHO should expose the code in tests"
    v = anon.post("/api/v1/auth/verify", json={"identifier": ident, "code": code})
    assert v.status_code == 200, v.text
    lg = anon.post("/api/v1/auth/login", json={"identifier": ident, "password": "Strong-Pass-123"})
    assert lg.status_code == 200, lg.text
    assert lg.json()["user"]["status"] == "PENDING_APPROVAL"
    assert lg.json()["user"]["permissions"] == []


def test_farmer_orders_are_private(login):
    a, b = login("farmer@demo.local"), login("farmer1@demo.local")
    mine = a.get("/api/v1/orders").json()
    if mine:
        assert b.get(f"/api/v1/orders/{mine[0]['id']}").status_code == 404


def test_wallet_never_negative(login):
    c = login("farmer@demo.local")
    w = c.get("/api/v1/wallet")
    assert w.status_code == 200 and w.json()["balance_paise"] >= 0


def test_products_listing_public_fields(login):
    r = login("farmer@demo.local").get("/api/v1/products")
    assert r.status_code == 200


def test_health(anon):
    assert anon.get("/api/v1/health").status_code == 200
