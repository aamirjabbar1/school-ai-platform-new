"""
Shared rate limiter.

Lives in its own module so route modules can apply limits without importing
`main` (which imports them). Requests are keyed by authenticated user rather
than by IP: a whole school shares one NAT address, so an IP-keyed limit would
throttle a class of thirty students joining at the same moment — exactly the
situation the classroom has to survive.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


def user_or_ip(request) -> str:
    """Rate-limit key: the user id from the bearer token, else the client IP.

    The token is read without verification purely to derive a bucket — the
    endpoint's own auth dependency is what actually authenticates the caller, so
    a forged token buys nothing but a different bucket name.
    """
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
        try:
            from jose import jwt
            claims = jwt.get_unverified_claims(token)
            user_id = claims.get("id")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=user_or_ip)
