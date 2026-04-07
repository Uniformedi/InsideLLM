from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from ..config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not settings.hub_secret:
        return "anonymous"
    if api_key != settings.hub_secret:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


async def verify_supervisor(api_key: str = Depends(verify_api_key)) -> str:
    """Placeholder — in production, validate the caller is in the supervisor list."""
    return api_key
