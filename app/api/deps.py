"""
deps.py — FastAPI dependency functions for authentication and authorisation.

'Dependencies' in FastAPI are reusable functions that run before a route
handler executes. They are injected via the Depends() helper. This file
provides the core security dependencies that protect API endpoints — any
route that imports one of these functions will automatically require a valid
JWT token before it can be called.
"""

from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_token
from app.services import auth_service

# HTTPBearer extracts the token from the "Authorization: Bearer <token>" header
# and makes it available to dependency functions automatically.
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Decode the JWT token from the request header and return the matching user.

    This is the foundational authentication dependency. Route handlers that
    need to know who is calling them should list this function in their
    Depends() arguments.

    Args:
        credentials: Automatically extracted from the Authorization header by
                     the HTTPBearer security scheme (injected by FastAPI).

    Returns:
        A dictionary representing the authenticated user record from the database.

    Raises:
        HTTPException (401 Unauthorized): if the token is missing, invalid,
        expired, or does not correspond to an existing user.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        # WWW-Authenticate header tells the client what authentication scheme is expected.
        headers={"WWW-Authenticate": "Bearer"},
    )

    # credentials.credentials holds the raw token string (without 'Bearer ').
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise credentials_exception

    # 'sub' (subject) is the standard JWT claim for the user's identity — here it stores the username.
    username: Optional[str] = payload.get("sub")
    if username is None:
        raise credentials_exception

    user = await auth_service.get_user_by_username(username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Extend get_current_user by also checking that the account is active.

    Depends(get_current_user) means FastAPI will run get_current_user first
    and pass its return value in as 'current_user' — dependencies can chain
    like this to build up layers of checks.

    Args:
        current_user: The authenticated user dict, resolved by get_current_user.

    Returns:
        The same user dict if their account_status is "active".

    Raises:
        HTTPException (400): if the user's account has been deactivated or suspended.
    """
    if current_user.get("account_status") != "active":
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_user_websocket(
    websocket: WebSocket
) -> Optional[Dict[str, Any]]:
    """
    Authenticate a WebSocket connection using a token passed as a query parameter.

    WebSocket connections cannot carry custom HTTP headers in the browser, so
    the JWT is passed as ?token=<value> in the connection URL instead.

    Args:
        websocket: The active WebSocket connection object provided by FastAPI.

    Returns:
        The authenticated and active user dict, or None if authentication fails
        (the socket is also closed with a policy-violation code in that case).
    """
    # WebSocket clients pass the token as a URL query parameter, e.g. /ws/chat?token=...
    token = websocket.query_params.get("token")
    if not token:
        # WS_1008_POLICY_VIOLATION is the standard WebSocket close code for auth failures.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    payload = decode_token(token)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    username: Optional[str] = payload.get("sub")
    if username is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    user = await auth_service.get_user_by_username(username)
    # Reject the connection if the user doesn't exist or their account is not active.
    if user is None or user.get("account_status") != "active":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None
    return user


class RoleChecker:
    """
    A callable dependency class that restricts a route to specific user roles.

    Usage example in a route:
        @router.get("/admin-only")
        async def admin_route(user = Depends(RoleChecker(["admin"]))):
            ...

    FastAPI calls an instance of this class as if it were a function, which
    triggers __call__ and performs the role check before the route body runs.
    """

    def __init__(self, allowed_roles: list):
        """
        Store the list of roles that are permitted to access the protected route.

        Args:
            allowed_roles: A list of role strings (e.g. ["admin", "doctor"]).
        """
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: Dict[str, Any] = Depends(get_current_active_user)):
        """
        Verify that the authenticated user holds one of the allowed roles.

        Args:
            current_user: The active user dict, resolved by get_current_active_user.

        Returns:
            The user dict if their role is permitted.

        Raises:
            HTTPException (403 Forbidden): if the user's role is not in allowed_roles.
        """
        if current_user.get("role") not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions"
            )
        return current_user
