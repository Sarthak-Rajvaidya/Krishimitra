"""Seeding.  python -m app.seed            -> base data only (roles, districts, reference data). Safe for production.
              python -m app.seed --demo     -> adds FICTIONAL demo users, products, orders, farms (refused in production)
              python -m app.seed --demo --reset   -> drops ALL tables first (demo databases only)

Demo data is flagged is_demo=True. Prices, stock, orders and finances are fictional. Government scheme and crop reference rows are seeded as
'needs verification' - an admin must check them against the official source before they are shown as verified.
"""
import argparse
import random
import secrets
from datetime import date, timedelta

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base, utcnow
from app.db.session import SessionLocal, engine
from app.models import *  # noqa
from app.permissions.rbac import PERMISSIONS, ROLE_BUNDLES
from app.services import checkout as co
from app.services.notify import notify  # noqa: F401

# sku, name, cat, type, pack, qty, unit, price_paise, cost_paise, gst_bp, crops, tags, safety, stock, threshold
PRODUCTS = [
    ("DEMO-UREA-45", "Urea 45 kg (sample)", "fertilizers", "FERTILIZER", "45 kg", 45, "kg", 26600, 22000, 500, "", "nitrogen,basal,top-dressing", "Store dry. Keep away from children.", 220, 30),
    ("DEMO-DAP-50", "DAP 50 kg (sample)", "fertilizers", "FERTILIZER", "50 kg", 50, "kg", 135000, 118000, 500, "", "phosphorus,nitrogen,basal", "Store dry. Wash hands after handling.", 120, 20),
    ("DEMO-NPK-19", "NPK 19:19:19 water-soluble 1 kg (sample)", "fertilizers", "FERTILIZER", "1 kg", 1, "kg", 28000, 21000, 500, "", "npk,water-soluble,fertigation", "Follow label. Avoid inhalation of dust.", 300, 40),
    ("DEMO-NPK-50", "NPK complex 50 kg (sample)", "fertilizers", "FERTILIZER", "50 kg", 50, "kg", 142000, 124000, 500, "", "npk,basal", "Store dry.", 80, 15),
    ("DEMO-ZN-1", "Zinc sulphate 1 kg (sample)", "micronutrients", "MICRONUTRIENT", "1 kg", 1, "kg", 14500, 10000, 1200, "", "zinc,micronutrient", "Avoid contact with eyes.", 150, 20),
    ("DEMO-FE-1", "Ferrous sulphate 1 kg (sample)", "micronutrients", "MICRONUTRIENT", "1 kg", 1, "kg", 9500, 6500, 1200, "", "iron,micronutrient", "Avoid contact with eyes.", 140, 20),
    ("DEMO-B-250", "Boron micronutrient 250 g (sample)", "micronutrients", "MICRONUTRIENT", "250 g", 0.25, "kg", 12000, 8200, 1200, "", "boron,micronutrient", "Keep out of reach of children.", 6, 10),
    ("DEMO-FUNG-A", "Demo fungicide A 250 ml (sample)", "crop-protection", "FUNGICIDE", "250 ml", 0.25, "l", 42000, 30000, 1800, "", "fungicide,demo", "Pesticide: read the registered label before use. Use protective gear.", 90, 15),
    ("DEMO-FUNG-B", "Demo fungicide B 100 g (sample)", "crop-protection", "FUNGICIDE", "100 g", 0.1, "kg", 31000, 22000, 1800, "", "fungicide,demo", "Pesticide: read the registered label before use. Use protective gear.", 75, 15),
    ("DEMO-INSECT-A", "Demo insecticide A 250 ml (sample)", "crop-protection", "INSECTICIDE", "250 ml", 0.25, "l", 38000, 27000, 1800, "", "insecticide,demo", "Pesticide: read the registered label before use. Use protective gear.", 85, 15),
    ("DEMO-INSECT-B", "Demo insecticide B 500 ml (sample)", "crop-protection", "INSECTICIDE", "500 ml", 0.5, "l", 69000, 50000, 1800, "", "insecticide,demo", "Pesticide: read the registered label before use. Use protective gear.", 60, 10),
    ("DEMO-SEED-1", "Open-pollinated vegetable seed 100 g (sample)", "seeds", "SEED", "100 g", 0.1, "kg", 18000, 12000, 0, "", "seed,vegetable", "Treated seed must not be eaten.", 110, 20),
    ("DEMO-SPRAY-16", "Knapsack sprayer 16 L (sample)", "equipment", "ACCESSORY", "1 unit", 1, "unit", 189900, 150000, 1800, "", "sprayer,accessory", "Rinse after use; do not reuse for drinking water.", 25, 5),
]


CATEGORIES = [("fertilizers", "Fertilizers"), ("crop-protection", "Crop Protection"), ("seeds", "Seeds"), ("micronutrients", "Micronutrients"),
              ("equipment", "Equipment & Accessories"), ("irrigation", "Irrigation & Pumps"), ("organic", "Organic Inputs")]

DISTRICTS = [("Pune", "Maharashtra", "MH-PUNE", "ACTIVE"), ("Nashik", "Maharashtra", "MH-NASH", "ACTIVE"), ("Solapur", "Maharashtra", "MH-SOLA", "PLANNED"),
             ("Ahmednagar", "Maharashtra", "MH-AHMD", "PLANNED")]
PINCODES = {"411001": "Pune", "422001": "Nashik", "413001": "Solapur", "414001": "Ahmednagar"}

# Generic textbook ranges. verified=False until an agronomist edits and verifies them for the region.
# crop, category, seasons, days, ph_min, ph_max, soils, water, moisture_low, temp_max, stages
CROPS = [
    ("Wheat", "CEREAL", "RABI", 120, 6.0, 7.5, "loam,clay loam", "MEDIUM", 35, 35), ("Rice", "CEREAL", "KHARIF", 130, 5.5, 7.0, "clay,clay loam", "HIGH", 60, 38),
    ("Maize", "CEREAL", "KHARIF,RABI", 100, 5.8, 7.5, "loam,sandy loam", "MEDIUM", 40, 38), ("Sorghum", "CEREAL", "KHARIF,RABI", 110, 6.0, 8.0, "black,loam", "LOW", 25, 40),
    ("Chickpea", "PULSE", "RABI", 110, 6.0, 8.0, "loam,black", "LOW", 25, 35), ("Pigeon pea", "PULSE", "KHARIF", 160, 6.0, 7.5, "black,loam", "LOW", 25, 38),
    ("Soybean", "OILSEED", "KHARIF", 100, 6.0, 7.5, "black,loam", "MEDIUM", 35, 36), ("Groundnut", "OILSEED", "KHARIF,ZAID", 110, 6.0, 7.0, "sandy loam,red", "MEDIUM", 30, 36),
    ("Tomato", "VEGETABLE", "KHARIF,RABI,ZAID", 110, 6.0, 7.0, "loam,sandy loam", "MEDIUM", 40, 35), ("Onion", "VEGETABLE", "RABI,KHARIF", 130, 6.0, 7.0, "loam,sandy loam", "MEDIUM", 35, 35),
    ("Cotton", "CASH", "KHARIF", 170, 6.0, 8.0, "black,loam", "MEDIUM", 30, 40), ("Sugarcane", "CASH", "KHARIF,ZAID", 330, 6.0, 8.0, "loam,clay loam", "HIGH", 50, 40),
]
STAGES = [{"name": "Germination", "until_pct": 12}, {"name": "Vegetative", "until_pct": 45}, {"name": "Flowering", "until_pct": 70}, {"name": "Grain / fruit filling", "until_pct": 90}]

# Official portals only; benefit amounts and rules deliberately NOT stated (they change). Admin verifies before publishing as verified.
SCHEMES = [
    ("PM-KISAN", "CENTRAL", "Income support scheme for farmer families run by the Government of India.", "https://pmkisan.gov.in"),
    ("PM Fasal Bima Yojana (crop insurance)", "CENTRAL", "Government-backed crop insurance against yield loss from natural causes.", "https://pmfby.gov.in"),
    ("Soil Health Card scheme", "CENTRAL", "Soil testing with crop-wise nutrient recommendations issued to farmers.", "https://soilhealth.dac.gov.in"),
    ("Kisan Credit Card (KCC)", "CENTRAL", "Short-term credit facility for farmers through banks.", "https://www.myscheme.gov.in"),
]


def reset() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_rbac(db) -> dict[str, Role]:
    perms = {}
    for code, desc in PERMISSIONS.items():
        p = db.scalar(select(Permission).where(Permission.code == code)) or Permission(code=code, description=desc)
        p.description = desc
        db.add(p)
        perms[code] = p
    db.flush()
    roles = {}
    for name, codes in ROLE_BUNDLES.items():
        r = db.scalar(select(Role).where(Role.name == RoleName(name)))
        if not r:                       # existing roles keep whatever the super admin configured
            r = Role(name=RoleName(name))
            r.permissions = [perms[c] for c in codes]
            db.add(r)
        roles[name] = r
    db.flush()
    return roles


def seed_base(db) -> dict:
    roles = seed_rbac(db)
    for name, state, code, st in DISTRICTS:
        if not db.scalar(select(District).where(District.code == code)):
            db.add(District(name=name, state=state, code=code, status=st))
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.code == "MAIN"))
    if not loc:
        loc = InventoryLocation(code="MAIN", name="KrishiMitra Warehouse")
        db.add(loc)
    db.flush()
    dist = {d.name: d.id for d in db.scalars(select(District))}
    for pc, dn in PINCODES.items():
        if not db.scalar(select(ServiceablePincode).where(ServiceablePincode.pincode == pc)):
            db.add(ServiceablePincode(pincode=pc, location_id=loc.id, district_id=dist.get(dn), delivery_fee_paise=4900))
    for slug, name in CATEGORIES:
        if not db.scalar(select(ProductCategory).where(ProductCategory.slug == slug)):
            db.add(ProductCategory(slug=slug, name=name, description=name))
    for c, cat, seasons, days, lo, hi, soils, water, mlow, tmax in CROPS:
        if not db.scalar(select(CropKnowledge).where(CropKnowledge.crop == c)):
            db.add(CropKnowledge(crop=c, category=cat, seasons=seasons, duration_days=days, ph_min=lo, ph_max=hi, soil_types=soils, water_need=water,
                                 moisture_low=mlow, temp_max_c=tmax, stages=STAGES, verified=False, notes="Generic reference range. Verify for your region."))
    for title, level, summary, url in SCHEMES:
        if not db.scalar(select(Content).where(Content.title == title)):
            db.add(Content(kind="SCHEME", title=title, level=level, summary=summary, url=url, source="Official portal (link)", needs_verification=True,
                           is_published=True, body="Check eligibility, benefits and documents on the official portal before applying."))
    for key, desc, en in [("crop_doctor.enabled", "Show Crop Doctor", True), ("iot.automation", "Allow automatic irrigation", True),
                          ("marketplace.suppliers", "Third-party suppliers can sell", True)]:
        if not db.scalar(select(FeatureFlag).where(FeatureFlag.key == key)):
            db.add(FeatureFlag(key=key, description=desc, enabled=en))
    if not db.scalar(select(ModelVersion).limit(1)):
        db.add(ModelVersion(name="crop-doctor", version="untrained-0", architecture="mobilenet_v3_small", is_active=False, is_trained=False, classes=[],
                            dataset_note="No model trained yet. Run ml/training/train.py (check dataset licence first)."))
    if not db.scalar(select(Promotion).where(Promotion.code == "WELCOME5")):
        db.add(Promotion(code="WELCOME5", description="5% off orders above Rs 500", percent_off_bp=500, max_discount_paise=10000, min_order_paise=50000))
    db.commit()
    return roles


def _user(db, roles, pw, email, mobile, name, role, district=None, status=UserStatus.ACTIVE):
    u = db.scalar(select(User).where(User.email == email))
    if u:
        return u
    u = User(email=email, phone=mobile, full_name=name, password_hash=pw, role_id=roles[role].id, is_demo=True, district_id=district, status=status,
             mobile_verified=True, email_verified=True, is_active=True, language="en",
             notif_prefs={"in_app": True, "sms": False, "email": False, "push": False, "muted_kinds": []}, privacy={"community_profile_public": True, "share_with_experts": True})
    db.add(u)
    db.flush()
    return u


def seed_demo(db) -> dict:
    roles = db.scalars(select(Role)).all()
    roles = {r.name.value: r for r in roles}
    rnd = random.Random(42)
    password = get_settings().demo_password or secrets.token_urlsafe(9)
    pw = hash_password(password)
    dist = {d.name: d.id for d in db.scalars(select(District))}
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.code == "MAIN"))
    cats = {c.slug: c for c in db.scalars(select(ProductCategory))}

    for sku, name, cat, ptype, pack, qty, unit, price, cost, gst, crops, tags, safety, stock, thr in PRODUCTS:
        if db.scalar(select(Product).where(Product.sku == sku)):
            continue
        p = Product(sku=sku, name=name, category_id=cats[cat].id, product_type=ProductType(ptype), pack_size=pack, unit_qty=qty, unit=unit, price_paise=price,
                    cost_paise=cost, gst_rate_bp=gst, crops=crops, use_tags=tags, safety_info=safety, description=f"{name}. SAMPLE listing: fictional price and stock.",
                    is_demo=True, approval_status="APPROVED")
        db.add(p)
        db.flush()
        db.add(ProductLabel(product_id=p.id, verified=False))
        db.add(InventoryBalance(product_id=p.id, location_id=loc.id, on_hand=stock, reorder_threshold=thr))
        db.add(InventoryTransaction(product_id=p.id, location_id=loc.id, txn_type=InvTxnType.RECEIPT, quantity_delta=stock, reference="DEMO-SEED", created_at=utcnow() - timedelta(days=70)))

    staff = [("admin@demo.local", "9000000001", "Demo Admin", "ADMIN", None), ("super@demo.local", "9000000002", "Demo Super Admin", "SUPER_ADMIN", None),
             ("finance@demo.local", "9000000003", "Demo Finance", "FINANCE", None), ("developer@demo.local", "9000000004", "Demo Developer", "DEVELOPER", None),
             ("founder@demo.local", "9000000005", "Demo Founder", "FOUNDER", None), ("district@demo.local", "9000000006", "Demo District Manager", "DISTRICT_MANAGER", dist["Pune"])]
    users = {e: _user(db, roles, pw, e, m, n, r, d) for e, m, n, r, d in staff}
    expert = _user(db, roles, pw, "expert@demo.local", "9000000010", "Dr. Demo Expert", "EXPERT", dist["Pune"])
    supplier = _user(db, roles, pw, "supplier@demo.local", "9000000011", "Demo Agro Traders", "SUPPLIER", dist["Pune"])
    partner = _user(db, roles, pw, "delivery@demo.local", "9000000012", "Demo Delivery Partner", "DELIVERY", dist["Pune"])
    lab = _user(db, roles, pw, "lab@demo.local", "9000000013", "Demo Soil Lab", "SOIL_CENTER", dist["Pune"])
    farmers = []
    names = [("farmer@demo.local", "9000000020", "Demo Farmer", "Pune", "411001")] + [(f"farmer{i}@demo.local", f"90000000{30 + i}", n, d, pc) for i, (n, d, pc) in enumerate(
        [("Ramesh Patil", "Pune", "411001"), ("Sunita Jadhav", "Nashik", "422001"), ("Anil Shinde", "Solapur", "413001"), ("Kavita More", "Ahmednagar", "414001"),
         ("Vijay Kale", "Pune", "411001"), ("Meena Pawar", "Nashik", "422001")], 1)]
    for e, m, n, d, pc in names:
        u = _user(db, roles, pw, e, m, n, "FARMER", dist[d])
        farmers.append((u, d, pc))
        if not db.scalar(select(FarmerProfile).where(FarmerProfile.user_id == u.id)):
            db.add(FarmerProfile(user_id=u.id, district=d, state="Maharashtra", primary_crops="tomato,onion"))
        if not db.scalar(select(Address).where(Address.user_id == u.id)):
            db.add(Address(user_id=u.id, line1="Demo Village Road", village="Demo Village", district=d, state="Maharashtra", pincode=pc, is_default=True))
        if not db.scalar(select(Farm).where(Farm.user_id == u.id)):
            f = Farm(user_id=u.id, name="Home farm", district=d, state="Maharashtra", latitude=18.52, longitude=73.86, area_acres=4.5, soil_type="loam",
                     irrigation_source="BOREWELL", is_demo=True)
            db.add(f)
            db.flush()
            db.add(Field(farm_id=f.id, name="North plot", area_acres=2.5, soil_type="loam"))
    db.flush()
    if not db.scalar(select(ExpertProfile).where(ExpertProfile.user_id == expert.id)):
        db.add(ExpertProfile(user_id=expert.id, qualification="M.Sc. Agriculture (demo)", specialization="tomato,onion,soil", experience_years=8, district="Pune", state="Maharashtra",
                             fee_paise=20000, bio="Demo profile.", languages="en,hi,mr", availability={"mon": ["10:00-13:00"], "thu": ["10:00-13:00"]}))
    if not db.scalar(select(SupplierProfile).where(SupplierProfile.user_id == supplier.id)):
        db.add(SupplierProfile(user_id=supplier.id, shop_name="Demo Agro Traders", district="Pune", state="Maharashtra", pincode="411001", product_categories="fertilizers,seeds"))
    if not db.scalar(select(DeliveryProfile).where(DeliveryProfile.user_id == partner.id)):
        db.add(DeliveryProfile(user_id=partner.id, vehicle_type="BIKE", vehicle_number="MH12-DEMO", licence_number="DEMO-0000"))
    if not db.scalar(select(SoilCenter).where(SoilCenter.user_id == lab.id)):
        db.add(SoilCenter(user_id=lab.id, name="Demo Soil Lab", district="Pune", state="Maharashtra", address="Demo Road", test_fee_paise=15000, is_demo=True))
    db.commit()

    # supplier's own listing (approved) with its own stock
    if not db.scalar(select(Product).where(Product.supplier_id == supplier.id)):
        sloc = co.supplier_location(db, supplier.id)
        for i, (nm, price) in enumerate([("Demo hybrid tomato seed 10 g (sample)", 25000), ("Demo vermicompost 5 kg (sample)", 18000)]):
            p = Product(sku=f"DEMO-S{i}", name=nm, category_id=cats["seeds" if i == 0 else "organic"].id, product_type=ProductType.SEED if i == 0 else ProductType.ORGANIC_FERTILIZER,
                        pack_size="1 pack", price_paise=price, cost_paise=0, gst_rate_bp=0, supplier_id=supplier.id, brand="Demo Brand", approval_status="APPROVED", is_demo=True,
                        description="SAMPLE supplier listing.")
            db.add(p)
            db.flush()
            db.add(InventoryBalance(product_id=p.id, location_id=sloc.id, on_hand=100))
    farm0 = db.scalar(select(Farm).where(Farm.user_id == farmers[0][0].id))
    if farm0 and not db.scalar(select(Crop).where(Crop.user_id == farmers[0][0].id)):
        c = Crop(user_id=farmers[0][0].id, farm_id=farm0.id, name="Tomato", category="VEGETABLE", season="KHARIF", area_acres=1.0, sowing_date=date.today() - timedelta(days=40),
                 expected_harvest_date=date.today() + timedelta(days=70), duration_days=110, status=CropStatus.ACTIVE, is_demo=True)
        db.add(c)
        db.flush()
        db.add(CropRecord(crop_id=c.id, user_id=c.user_id, kind="EXPENSE", on_date=date.today() - timedelta(days=38), product="Seeds and nursery", amount_paise=450000, is_demo=True))
        db.add(SoilReading(user_id=c.user_id, farm_id=farm0.id, on_date=date.today() - timedelta(days=30), ph=6.8, nitrogen=300, phosphorus=14, potassium=150, moisture=34, is_demo=True))
    if not db.scalar(select(Device).where(Device.owner_id == farmers[0][0].id)) and farm0:
        from app.services import iot
        uid, _tok, th = iot.new_credentials()
        d = Device(uid=uid, token_hash=th, owner_id=farmers[0][0].id, farm_id=farm0.id, name="Demo soil node", kind="COMBO", sensors=["soil_moisture", "temperature", "water_level"], is_demo=True)
        db.add(d)
        db.flush()
        db.add(IrrigationConfig(device_id=d.id))
        now = utcnow()
        for h in range(48, 0, -1):
            db.add(SensorReading(device_id=d.id, metric="soil_moisture", ts=now - timedelta(hours=h), value=round(45 + 15 * __import__("math").sin(h / 5) + rnd.random() * 3, 1)))
    for i, (g, t) in enumerate([("Tomato growers", "tomato"), ("Onion growers", "onion"), ("Organic farming", "organic")]):
        if not db.scalar(select(CommunityGroup).where(CommunityGroup.name == g)):
            db.add(CommunityGroup(name=g, topic=t, description="Demo group", is_demo=True))
    db.commit()

    if not db.scalar(select(Order).where(Order.is_demo == True).limit(1)):  # noqa: E712
        _seed_orders(db, rnd, [f for f, _, _ in farmers], users["admin@demo.local"], partner)
    return {"password": password}


def _seed_orders(db, rnd, farmers, admin, partner) -> None:
    products = db.scalars(select(Product).where(Product.is_demo == True, Product.approval_status == "APPROVED")).unique().all()  # noqa: E712
    today = utcnow()
    for day in range(45, 0, -1):
        for _ in range(rnd.choice([0, 1, 1, 2])):
            f = rnd.choice(farmers)
            cart = db.scalar(select(Cart).where(Cart.user_id == f.id)) or Cart(user_id=f.id)
            db.add(cart)
            db.flush()
            for p in rnd.sample(products, rnd.randint(1, 3)):
                if not db.scalar(select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == p.id)):
                    db.add(CartItem(cart_id=cart.id, product_id=p.id, quantity=rnd.randint(1, 3)))
            db.commit()
            addr = db.scalar(select(Address).where(Address.user_id == f.id))
            try:
                orders = co.place_order(db, f, addr.id, PaymentMode.COD, "WELCOME5" if rnd.random() < 0.25 else None, None)
            except Exception:
                # Roll back the failed checkout transaction. Do not manually
                # delete cart items here: the rollback restores the transaction
                # state, and the Cart.items relationship may still hold deleted
                # ORM instances from the failed checkout.
                db.rollback()
                continue
            when = today - timedelta(days=day, hours=rnd.randint(0, 10))
            for o in orders:
                _backdate(db, o.id, when)
                o = db.get(Order, o.id)
                if day < 3:
                    continue
                if rnd.random() < 0.08:
                    co.cancel_order(db, o, admin, "Demo cancellation")
                    continue
                for st in (OrderStatus.CONFIRMED, OrderStatus.PACKED, OrderStatus.READY_FOR_DISPATCH):
                    co.set_status(db, o, st, admin)
                d = db.scalar(select(Delivery).where(Delivery.order_id == o.id))
                d.partner_id, d.status, d.assigned_at = partner.id, DeliveryStatus.DELIVERED, when
                d.delivered_at = when + timedelta(days=1)
                co.mark_delivered(db, o, partner.id)
                _backdate(db, o.id, when)
    for m in range(3):
        for cat, amt in (("Warehouse rent", 4500000), ("Salaries", 12000000), ("Logistics", 2500000), ("Marketing", 1500000)):
            db.add(Expense(category=cat, description="DEMO expense", amount_paise=amt, incurred_on=today - timedelta(days=30 * m + 2), is_demo=True))
    db.commit()


def _backdate(db, order_id: int, when) -> None:
    db.execute(update(Order).where(Order.id == order_id).values(placed_at=when))
    db.execute(update(FinancialTransaction).where(FinancialTransaction.order_id == order_id).values(occurred_at=when))
    db.execute(update(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id).values(created_at=when))
    ref = db.scalar(select(Order.order_number).where(Order.id == order_id))
    db.execute(update(InventoryTransaction).where(InventoryTransaction.reference == ref).values(created_at=when))
    db.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="add fictional demo users and data (never in production)")
    ap.add_argument("--reset", action="store_true", help="DROP ALL TABLES first (demo databases only)")
    a = ap.parse_args()
    prod = get_settings().app_env == "production"
    if (a.demo or a.reset) and prod:
        raise SystemExit("Refusing to seed demo data or reset in production.")
    if a.reset:
        reset()
    else:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_base(db)
        info = seed_demo(db) if a.demo else None
    print("Base data ready (roles, permissions, districts, crop reference, scheme links).")
    if info:
        print("\nDemo logins (LOCAL ONLY), use the mobile or the email:")
        print("  farmer@demo.local 9000000020 | expert@demo.local | supplier@demo.local | delivery@demo.local | lab@demo.local")
        print("  district@demo.local | admin@demo.local | super@demo.local | finance@demo.local | developer@demo.local | founder@demo.local")
        print(f"Password for all: {info['password']}  (set DEMO_PASSWORD for a fixed value)\n")


if __name__ == "__main__":
    main()
