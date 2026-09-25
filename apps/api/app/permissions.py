from collections.abc import Callable
from functools import wraps

from fastapi import HTTPException, status

from app.models import Role

ROLE_RANK = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


def require_role(minimum: Role) -> Callable:
    """Mark a route's required organization role for centralized authorization."""
    def decorator(function: Callable) -> Callable:
        @wraps(function)
        def wrapped(*args, **kwargs):
            membership = kwargs.get("membership")
            if membership is None or ROLE_RANK[membership.role] < ROLE_RANK[minimum]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
            return function(*args, **kwargs)
        return wrapped
    return decorator
