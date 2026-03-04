from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network

import bcrypt
import pyotp
from jose import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    AuthFactor,
    AuthSession,
    IpAllowlistEntry,
    LoginAttempt,
    MfaBackupCode,
    PasswordHistory,
    PersonalDataRecord,
    Role,
    SecurityEvent,
    TenantSecuritySetting,
    User,
    UserRole,
)

class LoginRequest(BaseModel):
    tenant_id: uuid.UUID
    email: EmailStr
    password: str
    totp_code: str | None = None
    backup_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MfaSetupResponse(BaseModel):
    otpauth_uri: str
    backup_codes: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ErasureResponse(BaseModel):
    user_id: uuid.UUID
    anonymised_count: int


class AuthService:
    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _hash_backup_code(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _hash_password(self, password: str) -> str:
        rounds = min(max(settings.BCRYPT_ROUNDS, 4), 31)
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")

    def _verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False

    def _create_token(self, claims: dict, expires_delta: timedelta) -> str:
        payload = claims.copy()
        payload["exp"] = self._utcnow() + expires_delta
        payload["iat"] = self._utcnow()
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def _verify_password_policy(self, new_password: str) -> None:
        if len(new_password) < 12:
            raise ValueError("Password must be at least 12 characters")
        has_upper = any(ch.isupper() for ch in new_password)
        has_lower = any(ch.islower() for ch in new_password)
        has_digit = any(ch.isdigit() for ch in new_password)
        has_special = any(not ch.isalnum() for ch in new_password)
        if not all([has_upper, has_lower, has_digit, has_special]):
            raise ValueError("Password must include upper, lower, number, and special character")

    async def _roles_for_user(self, db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Role.role_name)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.tenant_id == tenant_id, UserRole.user_id == user_id)
        )
        rows = await db.execute(stmt)
        return [r[0] for r in rows.all()]

    async def _get_security_settings(self, db: AsyncSession, tenant_id: uuid.UUID) -> TenantSecuritySetting | None:
        res = await db.execute(
            select(TenantSecuritySetting).where(TenantSecuritySetting.tenant_id == tenant_id)
        )
        return res.scalar_one_or_none()

    async def _log_attempt(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        username: str,
        succeeded: bool,
        ip: str | None,
        user_agent: str | None,
        user_id: uuid.UUID | None = None,
    ) -> None:
        db.add(
            LoginAttempt(
                tenant_id=tenant_id,
                user_id=user_id,
                username=username,
                ip_address=ip,
                user_agent=user_agent,
                succeeded=succeeded,
            )
        )

    async def _count_recent_failed_attempts(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        username: str,
        minutes: int,
    ) -> int:
        since = self._utcnow() - timedelta(minutes=minutes)
        result = await db.execute(
            select(func.count(LoginAttempt.login_attempt_id)).where(
                LoginAttempt.tenant_id == tenant_id,
                LoginAttempt.username == username,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.created_at >= since,
            )
        )
        return int(result.scalar() or 0)

    async def _validate_mfa(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        totp_code: str | None,
        backup_code: str | None,
    ) -> bool:
        factor = (
            await db.execute(
                select(AuthFactor).where(
                    AuthFactor.tenant_id == tenant_id,
                    AuthFactor.user_id == user_id,
                    AuthFactor.factor_type == "totp",
                    AuthFactor.is_enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if factor is None or not factor.totp_secret_encrypted:
            return False

        totp = pyotp.TOTP(factor.totp_secret_encrypted)
        if totp_code and totp.verify(totp_code, valid_window=1):
            return True

        if backup_code:
            backup_hash = self._hash_backup_code(backup_code)
            backup_match = (
                await db.execute(
                    select(MfaBackupCode).where(
                        MfaBackupCode.tenant_id == tenant_id,
                        MfaBackupCode.user_id == user_id,
                        MfaBackupCode.code_hash == backup_hash,
                        MfaBackupCode.used_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if backup_match:
                backup_match.used_at = self._utcnow()
                return True

        return False

    async def login(
        self,
        db: AsyncSession,
        payload: LoginRequest,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[TokenResponse, str, dict]:
        failed_recent = await self._count_recent_failed_attempts(
            db,
            payload.tenant_id,
            payload.email,
            settings.ACCOUNT_LOCKOUT_MINUTES,
        )
        if failed_recent >= settings.ACCOUNT_LOCKOUT_FAILED_ATTEMPTS:
            raise ValueError("Account temporarily locked")

        user = (
            await db.execute(
                select(User).where(
                    User.tenant_id == payload.tenant_id,
                    User.username == payload.email,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if user is None or not self._verify_password(payload.password, user.password_hash):
            await self._log_attempt(db, payload.tenant_id, payload.email, False, ip, user_agent, user.user_id if user else None)
            total_failed = await self._count_recent_failed_attempts(
                db,
                payload.tenant_id,
                payload.email,
                24 * 60,
            )
            if total_failed >= settings.ACCOUNT_ALERT_FAILED_ATTEMPTS:
                db.add(
                    SecurityEvent(
                        tenant_id=payload.tenant_id,
                        actor_user_id=user.user_id if user else None,
                        event_type="account_failed_attempts_alert",
                        details=f"{payload.email} reached {total_failed} failed attempts",
                    )
                )
            raise ValueError("Invalid credentials")

        roles = await self._roles_for_user(db, payload.tenant_id, user.user_id)
        sec = await self._get_security_settings(db, payload.tenant_id)
        mfa_required = (
            "system_admin" in roles
            or "cfo" in roles
            or (sec.mfa_required_for_all_users if sec else False)
        )
        if mfa_required:
            if not await self._validate_mfa(db, payload.tenant_id, user.user_id, payload.totp_code, payload.backup_code):
                await self._log_attempt(db, payload.tenant_id, payload.email, False, ip, user_agent, user.user_id)
                raise ValueError("MFA required")

        await self._log_attempt(db, payload.tenant_id, payload.email, True, ip, user_agent, user.user_id)
        user.last_login_at = self._utcnow()

        session_limit = sec.concurrent_session_limit if sec else settings.DEFAULT_CONCURRENT_SESSION_LIMIT
        current_sessions = (
            await db.execute(
                select(AuthSession)
                .where(
                    AuthSession.tenant_id == payload.tenant_id,
                    AuthSession.user_id == user.user_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > self._utcnow(),
                )
                .order_by(AuthSession.issued_at.asc())
            )
        ).scalars().all()

        if len(current_sessions) >= session_limit:
            revoke_count = len(current_sessions) - session_limit + 1
            for s in current_sessions[:revoke_count]:
                s.revoked_at = self._utcnow()

        session_id = uuid.uuid4()
        jti_access = secrets.token_hex(16)
        jti_refresh = secrets.token_hex(16)

        access_token = self._create_token(
            {
                "sub": str(user.user_id),
                "tenant_id": str(payload.tenant_id),
                "roles": roles,
                "sid": str(session_id),
                "jti": jti_access,
                "type": "access",
            },
            timedelta(minutes=settings.JWT_ACCESS_TOKEN_TTL_MINUTES),
        )

        refresh_token = self._create_token(
            {
                "sub": str(user.user_id),
                "tenant_id": str(payload.tenant_id),
                "roles": roles,
                "sid": str(session_id),
                "jti": jti_refresh,
                "type": "refresh",
            },
            timedelta(days=settings.JWT_REFRESH_TOKEN_TTL_DAYS),
        )

        db.add(
            AuthSession(
                session_id=session_id,
                tenant_id=payload.tenant_id,
                user_id=user.user_id,
                jwt_id=jti_refresh,
                ip_address=ip,
                user_agent=user_agent,
                expires_at=self._utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_TTL_DAYS),
            )
        )

        return (
            TokenResponse(access_token=access_token, expires_in=settings.JWT_ACCESS_TOKEN_TTL_MINUTES * 60),
            refresh_token,
            {"roles": roles, "tenant_id": str(payload.tenant_id), "user_id": str(user.user_id), "session_id": str(session_id)},
        )

    async def setup_mfa(self, db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, email: str) -> MfaSetupResponse:
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="KuberaTreasury")

        factor = (
            await db.execute(
                select(AuthFactor).where(
                    AuthFactor.tenant_id == tenant_id,
                    AuthFactor.user_id == user_id,
                    AuthFactor.factor_type == "totp",
                )
            )
        ).scalar_one_or_none()
        if factor is None:
            factor = AuthFactor(
                tenant_id=tenant_id,
                user_id=user_id,
                factor_type="totp",
                totp_secret_encrypted=secret,
                is_enabled=False,
            )
            db.add(factor)
        else:
            factor.totp_secret_encrypted = secret
            factor.is_enabled = False

        await db.execute(
            update(MfaBackupCode)
            .where(MfaBackupCode.tenant_id == tenant_id, MfaBackupCode.user_id == user_id)
            .values(used_at=self._utcnow())
        )

        backup_codes: list[str] = []
        for _ in range(10):
            code = secrets.token_hex(4)
            backup_codes.append(code)
            db.add(
                MfaBackupCode(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    code_hash=self._hash_backup_code(code),
                )
            )

        return MfaSetupResponse(otpauth_uri=uri, backup_codes=backup_codes)

    async def verify_mfa_setup(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        code: str,
        roles: list[str],
    ) -> bool:
        factor = (
            await db.execute(
                select(AuthFactor).where(
                    AuthFactor.tenant_id == tenant_id,
                    AuthFactor.user_id == user_id,
                    AuthFactor.factor_type == "totp",
                )
            )
        ).scalar_one_or_none()
        if factor is None or not factor.totp_secret_encrypted:
            return False

        if pyotp.TOTP(factor.totp_secret_encrypted).verify(code, valid_window=1):
            factor.is_enabled = True
            return True

        if "system_admin" in roles or "cfo" in roles:
            factor.is_enabled = True
        return False

    async def refresh_access_token(self, db: AsyncSession, refresh_payload: dict, ip: str | None, ua: str | None) -> TokenResponse:
        if refresh_payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")

        sid = uuid.UUID(str(refresh_payload["sid"]))
        jti = str(refresh_payload["jti"])
        tenant_id = uuid.UUID(str(refresh_payload["tenant_id"]))
        user_id = uuid.UUID(str(refresh_payload["sub"]))

        session = (
            await db.execute(
                select(AuthSession).where(
                    AuthSession.session_id == sid,
                    AuthSession.tenant_id == tenant_id,
                    AuthSession.user_id == user_id,
                    AuthSession.jwt_id == jti,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > self._utcnow(),
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise ValueError("Session revoked or expired")

        sec = await self._get_security_settings(db, tenant_id)
        inactivity = sec.inactivity_timeout_minutes if sec else settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES
        if session.issued_at and (self._utcnow() - session.issued_at) > timedelta(minutes=inactivity):
            session.revoked_at = self._utcnow()
            raise ValueError("Session inactive timeout")

        session.ip_address = ip
        session.user_agent = ua
        session.issued_at = self._utcnow()

        token = self._create_token(
            {
                "sub": str(user_id),
                "tenant_id": str(tenant_id),
                "roles": refresh_payload.get("roles", []),
                "sid": str(sid),
                "jti": secrets.token_hex(16),
                "type": "access",
            },
            timedelta(minutes=settings.JWT_ACCESS_TOKEN_TTL_MINUTES),
        )
        return TokenResponse(access_token=token, expires_in=settings.JWT_ACCESS_TOKEN_TTL_MINUTES * 60)

    async def revoke_all_sessions(self, db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID) -> int:
        sessions = (
            await db.execute(
                select(AuthSession).where(
                    AuthSession.tenant_id == tenant_id,
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        now = self._utcnow()
        for s in sessions:
            s.revoked_at = now
        db.add(
            SecurityEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                event_type="force_logout_all_sessions",
                details=f"sessions_revoked={len(sessions)} user_id={user_id}",
            )
        )
        return len(sessions)

    async def change_password(self, db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: ChangePasswordRequest) -> None:
        user = (
            await db.execute(select(User).where(User.tenant_id == tenant_id, User.user_id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("User not found")

        if not self._verify_password(payload.current_password, user.password_hash):
            raise ValueError("Current password invalid")

        self._verify_password_policy(payload.new_password)

        history_rows = (
            await db.execute(
                select(PasswordHistory)
                .where(PasswordHistory.tenant_id == tenant_id, PasswordHistory.user_id == user_id)
                .order_by(PasswordHistory.created_at.desc())
                .limit(12)
            )
        ).scalars().all()
        if any(self._verify_password(payload.new_password, h.password_hash) for h in history_rows):
            raise ValueError("Cannot reuse last 12 passwords")

        new_hash = self._hash_password(payload.new_password)
        user.password_hash = new_hash
        db.add(PasswordHistory(tenant_id=tenant_id, user_id=user_id, password_hash=new_hash))

    async def erase_personal_data(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        target_user_id: uuid.UUID,
        requested_by: uuid.UUID,
    ) -> ErasureResponse:
        records = (
            await db.execute(
                select(PersonalDataRecord).where(
                    PersonalDataRecord.tenant_id == tenant_id,
                    PersonalDataRecord.subject_type == f"user:{target_user_id}",
                    PersonalDataRecord.erased_at.is_(None),
                )
            )
        ).scalars().all()

        count = 0
        now = self._utcnow()
        for record in records:
            record.full_name = None
            record.email = None
            record.phone = None
            record.address_line_1 = None
            record.address_line_2 = None
            record.city = None
            record.postcode = None
            record.country_code = None
            record.erased_at = now
            count += 1

        db.add(
            SecurityEvent(
                tenant_id=tenant_id,
                actor_user_id=requested_by,
                event_type="personal_data_erasure",
                details=f"target_user_id={target_user_id} anonymised_count={count}",
            )
        )

        return ErasureResponse(user_id=target_user_id, anonymised_count=count)

    async def is_ip_allowed(self, db: AsyncSession, tenant_id: uuid.UUID, remote_ip: str) -> bool:
        sec = await self._get_security_settings(db, tenant_id)
        if sec is None or not sec.ip_allowlist_enforced:
            return True

        entries = (
            await db.execute(select(IpAllowlistEntry).where(IpAllowlistEntry.tenant_id == tenant_id))
        ).scalars().all()
        if not entries:
            return True

        client_ip = ip_address(remote_ip)
        for entry in entries:
            if client_ip in ip_network(entry.cidr, strict=False):
                return True
        return False
