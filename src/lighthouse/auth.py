"""Authentication: verify the Supabase access token sent by the web app."""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lighthouse.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UUID:
    """The signed-in user's id, taken from a verified `Authorization: Bearer <jwt>` header."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing access token")
    if credentials is None:
        raise unauthorized
    try:
        # Supabase Auth (GoTrue) signs with HS256 and sets aud="authenticated" for signed-in users.
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
        return UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None


CurrentUser = Annotated[UUID, Depends(current_user_id)]
