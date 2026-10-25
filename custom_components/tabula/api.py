from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, FormData


class TabulaError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after


class TabulaAuthError(TabulaError):
    pass


class TabulaRateLimitError(TabulaError):
    pass


class TabulaNotFoundError(TabulaError):
    pass


class TabulaConflictError(TabulaError):
    pass


@dataclass(slots=True)
class RateLimit:
    limit: int | None = None
    remaining: int | None = None


@dataclass(slots=True)
class ApiKeyInfo:
    id: str
    name: str
    created_at: str
    expires_at: str | None


@dataclass(slots=True)
class CompanyInfo:
    id: str
    name: str | None


@dataclass(slots=True)
class InspectResult:
    api_key: ApiKeyInfo
    company: CompanyInfo


def _parse_retry_after(resp: ClientResponse) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # Tabula should always send a number, but eh


class TabulaClient:
    def __init__(
        self,
        session: ClientSession,
        api_key: str,
        base_url: str = "https://api.tabula.de",
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.rate_limit = RateLimit()
        self.last_request_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _remember_headers(self, resp: ClientResponse) -> None:
        self.last_request_id = resp.headers.get("Request-Id")
        limit = resp.headers.get("X-RateLimit-Limit")
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if limit is not None:
            try:
                self.rate_limit.limit = int(limit)
            except ValueError:
                pass
        if remaining is not None:
            try:
                self.rate_limit.remaining = int(remaining)
            except ValueError:
                pass
        # print(resp.status, self.rate_limit)  # noisy

    async def _raise_for_problem(self, resp: ClientResponse) -> None:
        self._remember_headers(resp)
        try:
            problem = await resp.json(content_type=None)
        except Exception:
            problem = {}
        if not isinstance(problem, dict):
            problem = {}

        err_code = problem.get("code")
        message = problem.get("detail") or resp.reason
        req_id = problem.get("requestId") or self.last_request_id
        wait = _parse_retry_after(resp)
        http_status = resp.status

        if http_status == 401 or err_code == "invalid_api_key":
            raise TabulaAuthError(
                message or "Invalid API key",
                code=err_code, status=http_status, request_id=req_id,
            )
        if http_status == 429 or err_code == "rate_limited":
            raise TabulaRateLimitError(
                message or "Rate limited",
                code=err_code, status=http_status, request_id=req_id,
                retry_after=wait,
            )
        if http_status == 404 or err_code in {"not_found", "upload_not_found"}:
            raise TabulaNotFoundError(
                message or "Not found",
                code=err_code, status=http_status, request_id=req_id,
            )
        if http_status == 409 or err_code in {
            "external_id_conflict", "company_not_ready"
        }:
            raise TabulaConflictError(
                message or "Conflict",
                code=err_code, status=http_status, request_id=req_id,
            )
        raise TabulaError(
            message or f"HTTP {http_status}",
            code=err_code, status=http_status, request_id=req_id,
            retry_after=wait,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        form: FormData | None = None,
    ) -> tuple[Any, float | None]:
        try:
            async with self._session.request(
                method,
                self._url(path),
                headers=self._headers(),
                data=form,
            ) as resp:
                self._remember_headers(resp)
                retry_after = _parse_retry_after(resp)
                if resp.status >= 400:
                    await self._raise_for_problem(resp)
                if resp.status == 204:
                    return None, retry_after
                return await resp.json(content_type=None), retry_after
        except (TimeoutError, ClientError) as err:
            raise TabulaError(str(err)) from err

    async def inspect(self) -> InspectResult:
        body, _ = await self._request("GET", "/v1/auth/keys/inspect")
        key = body["apiKey"]
        company = body["company"]
        return InspectResult(
            api_key=ApiKeyInfo(
                id=key["id"],
                name=key["name"],
                created_at=key["createdAt"],
                expires_at=key.get("expiresAt"),
            ),
            company=CompanyInfo(
                id=company["id"],
                name=company.get("name"),
            ),
        )

    async def create_upload(
        self,
        *,
        content: bytes,
        filename: str,
        document_type: str = "auto",
        external_id: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        form = FormData()
        form.add_field(
            "file",
            content,
            filename=filename,
            content_type=content_type or "application/octet-stream",
        )
        form.add_field("documentType", document_type)
        if external_id:
            form.add_field("externalId", external_id)
        upload, _ = await self._request("POST", "/v1/uploads", form=form)
        return upload

    async def get_upload(self, upload_id: str) -> tuple[dict[str, Any], float | None]:
        return await self._request("GET", f"/v1/uploads/{upload_id}")

    async def create_upload_batch(
        self,
        *,
        content: bytes,
        filename: str,
        document_type: str = "auto",
        external_id: str | None = None,
    ) -> dict[str, Any]:
        form = FormData()
        form.add_field(
            "file",
            content,
            filename=filename,
            content_type="application/zip",
        )
        form.add_field("documentType", document_type)
        if external_id:
            form.add_field("externalId", external_id)
        batch, _ = await self._request("POST", "/v1/uploads/batches", form=form)
        return batch

    async def get_upload_batch(
        self, batch_id: str
    ) -> tuple[dict[str, Any], float | None]:
        return await self._request("GET", f"/v1/uploads/batches/{batch_id}")
