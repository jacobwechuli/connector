import hmac
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.database import Base, engine
from app.core.config import get_settings
import app.models  # ensure metadata registration


Base.metadata.create_all(bind=engine)
app = FastAPI(title="AI Portfolio Maintainer", version="1.0.0")

@app.middleware("http")
async def admin_api_key(request: Request, call_next):
    """Protect dashboard/API calls when DASHBOARD_API_KEY is configured."""
    # Always pass preflight requests straight through – CORS middleware
    # already handled them above.
    if request.method == "OPTIONS":
        return await call_next(request)

    key = get_settings().dashboard_api_key
    public = request.url.path in {
        "/health",
        "/api/health",
        "/webhooks/github",
        "/api/webhooks/github",
        "/docs",
        "/openapi.json",
    }
    if key and not public:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(supplied, key):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

    return await call_next(request)


# Add CORS after function middleware. Starlette wraps the most recently added
# middleware on the outside, which ensures even auth failures carry CORS headers.
_settings = get_settings()
_origins = [origin.strip() for origin in _settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router, prefix="/api")
app.include_router(router, prefix="")
