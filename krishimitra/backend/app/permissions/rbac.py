"""Permission catalogue and default role bundles. Deny by default.
Bundles are seeded into the DB and editable by the SUPER_ADMIN through /superadmin/roles.
Ownership (e.g. "this farm belongs to me") is checked separately inside each endpoint."""

PERMISSIONS: dict[str, str] = {
    # --- farmer ---
    "shop.use": "Browse, cart, wishlist, checkout, orders",
    "ai.use": "Crop Doctor, AI assistant, advisory",
    "farm.manage": "Own farms, fields, crops, soil data, records",
    "iot.own": "Own IoT devices and irrigation",
    "soil.book": "Book soil tests",
    "expert.consult": "Book and chat with experts",
    "machine.rent": "Rent machines",
    "wallet.use": "Wallet and payments",
    "community.use": "Community posts and groups",
    "support.use": "Support tickets and complaints",
    # --- expert / supplier / delivery / soil centre ---
    "expert.practice": "Expert dashboard, appointments, advice",
    "supplier.manage": "Supplier portal: own products, orders, analytics",
    "machine.manage": "List and manage own machines",
    "delivery.work": "Delivery partner app",
    "soilcenter.work": "Soil testing centre console",
    # --- district ---
    "district.manage": "District dashboard limited to own district",
    # --- admin ---
    "users.manage": "View, create, approve, suspend users",
    "approvals.manage": "Approve registrations, documents, products, machines",
    "catalog.manage": "Platform catalogue, categories, brands",
    "inventory.manage": "Adjust platform stock",
    "orders.manage": "Process, cancel, refund any order",
    "orders.view_all": "View all orders",
    "customers.view": "View customers",
    "promotions.manage": "Manage promotions",
    "delivery.manage": "Assign and monitor deliveries, delivery areas",
    "iot.admin": "All devices, sensors, maintenance records",
    "content.manage": "CMS: articles, schemes, guides, announcements",
    "moderation.manage": "Moderate community and reviews",
    "support.manage": "Handle and assign tickets",
    "reports.operational": "Operational reports",
    "reports.admin": "Platform reports (users, marketplace, IoT...)",
    "users.manage_roles": "Change user roles",
    "audit.view": "View audit records",
    "knowledge.manage": "Upload/ingest knowledge documents",
    "knowledge.view": "View knowledge documents",
    # --- finance / founder / developer ---
    "finance.view": "Finance dashboards, ledger, exports",
    "finance.write": "Record expenses and refunds",
    "executive.view": "Executive overview",
    "executive.sensitive": "Sensitive executive reports (audited)",
    "system.view": "Service health, models, flags, logs",
    "system.configure": "Feature flags, model versions",
    # --- super admin ---
    "superadmin.manage": "Admin accounts, roles, districts, franchises, platform settings, broadcasts",
}

_FARMER = ["shop.use", "ai.use", "farm.manage", "iot.own", "soil.book", "expert.consult", "machine.rent", "machine.manage",
           "wallet.use", "community.use", "support.use"]
_ADMIN = ["users.manage", "approvals.manage", "catalog.manage", "inventory.manage", "orders.manage", "orders.view_all",
          "customers.view", "promotions.manage", "delivery.manage", "iot.admin", "content.manage", "moderation.manage",
          "support.manage", "reports.operational", "reports.admin", "users.manage_roles", "audit.view", "knowledge.view",
          "knowledge.manage"]

ROLE_BUNDLES: dict[str, list[str]] = {
    "FARMER": _FARMER,
    "EXPERT": ["expert.practice", "community.use", "support.use", "wallet.use", "ai.use"],
    "SUPPLIER": ["supplier.manage", "machine.manage", "community.use", "support.use", "wallet.use"],
    "DELIVERY": ["delivery.work", "support.use", "wallet.use"],
    "SOIL_CENTER": ["soilcenter.work", "support.use"],
    "DISTRICT_MANAGER": ["district.manage", "reports.operational", "support.use", "delivery.manage", "audit.view"],
    "ADMIN": _ADMIN,
    "SUPER_ADMIN": sorted(PERMISSIONS),      # everything
    "FINANCE": ["finance.view", "finance.write", "reports.operational"],
    "DEVELOPER": ["system.view", "system.configure", "knowledge.manage", "knowledge.view", "audit.view", "iot.admin"],
    "FOUNDER": ["executive.view", "executive.sensitive", "reports.operational", "finance.view", "system.view", "knowledge.view"],
}

SELF_REGISTER_ROLES = ("FARMER", "EXPERT", "SUPPLIER", "DELIVERY", "SOIL_CENTER")
NEEDS_APPROVAL = ("EXPERT", "SUPPLIER", "DELIVERY", "SOIL_CENTER")
STAFF_ROLES = ("DISTRICT_MANAGER", "ADMIN", "SUPER_ADMIN", "FINANCE", "DEVELOPER", "FOUNDER")
PORTAL_PATH = {"FARMER": "/", "EXPERT": "/expert", "SUPPLIER": "/supplier", "DELIVERY": "/delivery", "SOIL_CENTER": "/soil-center",
               "DISTRICT_MANAGER": "/district", "ADMIN": "/admin", "SUPER_ADMIN": "/super", "FINANCE": "/finance",
               "DEVELOPER": "/developer", "FOUNDER": "/founder"}
