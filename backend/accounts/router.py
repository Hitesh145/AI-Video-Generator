"""HTTP endpoints for signup, login, logout and "who am I", plus the login dependency."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from accounts.service import (
    SESSION_TTL,
    AccountService,
    EmailTaken,
    InvalidLogin,
    InvalidSignup,
    TooManyAttempts,
    UserInfo,
)

SESSION_COOKIE = "edugen_session"


class Credentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    user_id: str
    email: str


def _set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def create_auth_router(service: AccountService, cookie_secure: bool = False) -> APIRouter:
    router = APIRouter(prefix="/auth")
    current_user = create_current_user_dependency(service)

    @router.post("/signup", status_code=201, response_model=UserOut)
    def signup(body: Credentials, response: Response) -> UserOut:
        try:
            user, token = service.signup(body.email, body.password)
        except InvalidSignup as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except EmailTaken:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        _set_session_cookie(response, token, cookie_secure)
        return UserOut(user_id=user.user_id, email=user.email)

    @router.post("/login", response_model=UserOut)
    def login(body: Credentials, request: Request, response: Response) -> UserOut:
        client_ip = request.client.host if request.client else "unknown"
        try:
            user, token = service.login(body.email, body.password, client_ip)
        except TooManyAttempts as exc:
            raise HTTPException(
                status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
            )
        except InvalidLogin:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        _set_session_cookie(response, token, cookie_secure)
        return UserOut(user_id=user.user_id, email=user.email)

    @router.post("/logout", status_code=204)
    def logout(request: Request) -> Response:
        service.logout(request.cookies.get(SESSION_COOKIE, ""))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure)
        return response

    @router.get("/me", response_model=UserOut)
    def me(user: UserInfo = Depends(current_user)) -> UserOut:
        return UserOut(user_id=user.user_id, email=user.email)

    return router


def create_current_user_dependency(service: AccountService) -> Callable[[Request], UserInfo]:
    def current_user(request: Request) -> UserInfo:
        user = service.user_for_token(request.cookies.get(SESSION_COOKIE, ""))
        if user is None:
            raise HTTPException(status_code=401, detail="Not logged in")
        return user

    return current_user
