from fastapi import APIRouter
from app.core.config import settings
from app.schemas.job import HealthResponse
import redis

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health status of the API and its dependencies",
)
async def health_check():
    """
    Health check endpoint that verifies all services are operational.
    """
    services = {
        "api": "healthy",
        "redis": "unknown",
        "database": "unknown",
    }
    
    # Check Redis connection
    try:
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        services["redis"] = "healthy"
    except Exception:
        services["redis"] = "unhealthy"
    
    # Check database connection
    try:
        from app.core.database import engine
        from sqlalchemy import text
        
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        services["database"] = "healthy"
    except Exception:
        services["database"] = "unhealthy"
    
    overall_status = "healthy" if all(
        s == "healthy" for s in services.values()
    ) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        version="1.0.0",
        services=services,
    )
