from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from intric.main.config import get_settings


class JWTMeta(BaseModel):
    iss: str = get_settings().jwt_issuer  # who issued it
    aud: str = get_settings().jwt_audience  # who it's intended for
    iat: float = datetime.timestamp(datetime.utcnow())  # issued at time
    exp: float = datetime.timestamp(
        datetime.utcnow() + timedelta(minutes=get_settings().jwt_expiry_time)
    )  # expiry time


class JWTCreds(BaseModel):
    """How we'll identify users"""

    sub: EmailStr
    username: Optional[str] = None


class JWTPayload(JWTMeta, JWTCreds):
    """
    JWT Payload right before it's encoded - combine meta and username
    """

    pass


class AccessToken(BaseModel):
    access_token: str
    token_type: str


class ApiKeyPublic(BaseModel):
    truncated_key: str


class ApiKey(ApiKeyPublic):
    key: str


class ApiKeyCreated(ApiKey):
    hashed_key: str


class ApiKeyInDB(ApiKey):
    user_id: Optional[UUID]
    assistant_id: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class CreateUserResponse(BaseModel):
    token: AccessToken
    api_key: ApiKey


class OpenIdConnectLogin(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str
    client_id: str
    grant_type: str = "authorization_code"
    scope: str = "openid"
    nonce: Optional[str] = None
