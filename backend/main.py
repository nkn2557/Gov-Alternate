from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router as v1_router
from app.api.admin.api import api_router as admin_router

app = FastAPI(title="Municipality Procedure Support API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "ok", "project": settings.PROJECT_ID}

app.include_router(v1_router, prefix="/v1")
app.include_router(admin_router, prefix="/admin")
