from fastapi import APIRouter

from app.api.v1 import (account, admin, advisory, auth, catalog, community, content, crop, delivery, experts, farm, finance, founder, iot,
                        market, people_admin, reports, shop, soilcenter, superadmin, supplier, support, system)

api_router = APIRouter(prefix="/api/v1")
for m in (auth, account, farm, soilcenter, catalog, shop, market, supplier, delivery, iot, experts, community, content, support, crop, advisory,
          admin, people_admin, superadmin, reports, finance, founder, system):
    api_router.include_router(m.router)
