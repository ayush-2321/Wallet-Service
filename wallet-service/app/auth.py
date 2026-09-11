import uuid

from fastapi import Header, HTTPException

# The caller is identified by a per-user bearer token. We derive a stable user id
# from the token with UUIDv5 (deterministic), so the same token always maps to the
# same user/wallet without needing a separate users table or a signup race.
_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def require_user(authorization: str = Header(..., alias="Authorization")) -> uuid.UUID:
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing or malformed bearer token")
    return uuid.uuid5(_NAMESPACE, token)
