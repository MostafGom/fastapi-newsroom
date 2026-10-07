from fastapi import APIRouter

from newsroom.api.v1 import account, admin, auth, collect, public, publishing

router = APIRouter(prefix="/api/v1")
router.include_router(public.router)
router.include_router(collect.router)
router.include_router(auth.router)
router.include_router(account.router)
router.include_router(admin.router)
router.include_router(publishing.router)
