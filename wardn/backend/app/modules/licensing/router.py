from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.licensing.exceptions import InvalidLicenseLeaseError, LicenseRenewalError
from app.modules.licensing.schemas import LicenseLeaseImport, LicenseStatus
from app.modules.licensing.service import (
    get_license_status,
    import_signed_lease,
    renew_license,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/license", tags=["license"])


def licensing_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, InvalidLicenseLeaseError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("", response_model=LicenseStatus, operation_id="license_status")
async def license_status_route(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LicenseStatus:
    try:
        return await get_license_status(session, current_user)
    except PermissionError as exc:
        raise licensing_http_error(exc) from exc


@router.put("/lease", response_model=LicenseStatus, operation_id="license_lease_import")
async def import_license_lease_route(
    payload: LicenseLeaseImport,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LicenseStatus:
    try:
        return await import_signed_lease(
            session,
            current_user,
            payload.signed_lease,
            renewal_token=payload.renewal_token,
        )
    except (PermissionError, InvalidLicenseLeaseError) as exc:
        raise licensing_http_error(exc) from exc


@router.post("/renew", response_model=LicenseStatus, operation_id="license_renew")
async def renew_license_route(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LicenseStatus:
    try:
        return await renew_license(session, current_user)
    except (PermissionError, InvalidLicenseLeaseError, LicenseRenewalError) as exc:
        raise licensing_http_error(exc) from exc
