import os
import json
import logging
from typing import Optional, Literal

import gspread
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone, timedelta

# =========================
# Logging
# =========================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("restaurant-api")

# =========================
# Timezone (KST)
# =========================
KST = timezone(timedelta(hours=9))

# =========================
# FastAPI App
# =========================
app = FastAPI(title="Restaurant Reservation API", version="1.2.0")

# =========================
# Raw body capture (for 422 debug)
# =========================
@app.middleware("http")
async def capture_raw_body(request: Request, call_next):
    if request.url.path in ("/reservation/create", "/reservation/cancel") and request.method == "POST":
        body = await request.body()
        request.state.raw_body = body

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive

    return await call_next(request)

def _json_safe_errors(errors):
    safe = []
    for e in errors:
        e2 = dict(e)
        ctx = e2.get("ctx")
        if isinstance(ctx, dict):
            ctx2 = dict(ctx)
            if "error" in ctx2:
                ctx2["error"] = str(ctx2["error"])  # ValueError -> string
            e2["ctx"] = ctx2
        safe.append(e2)
    return safe

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw = getattr(request.state, "raw_body", b"")
    raw_text = raw.decode("utf-8", errors="replace")
    errs = _json_safe_errors(exc.errors())

    logger.warning(
        "422 ValidationError path=%s errors=%s raw_body=%s",
        request.url.path, errs, raw_text
    )
    return JSONResponse(status_code=422, content={"detail": errs})

# =========================
# CORS
# =========================
cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = ["*"] if cors_origins.strip() == "*" else [
    o.strip() for o in cors_origins.split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Google Sheets Globals
# =========================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ENV_GOOGLE_KEY = "GOOGLE_SERVICE_KEY"
ENV_SHEET_ID = "SPREADSHEET_ID"
ENV_WORKSHEET = "WORKSHEET_NAME"  # optional

gc: Optional[gspread.Client] = None
worksheet = None

def _get_env(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v

def _init_gspread() -> None:
    global gc, worksheet

    raw_key = _get_env(ENV_GOOGLE_KEY, required=True)
    spreadsheet_id = _get_env(ENV_SHEET_ID, required=True)
    worksheet_name = _get_env(ENV_WORKSHEET, required=False, default="")

    try:
        service_account_info = json.loads(raw_key)
    except Exception as e:
        raise RuntimeError(f"{ENV_GOOGLE_KEY} is not valid JSON in env.") from e

    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(spreadsheet_id)
    worksheet = sh.worksheet(worksheet_name.strip()) if worksheet_name.strip() else sh.sheet1

    logger.info(
        "Google Sheets initialized. spreadsheet_id=%s worksheet=%s",
        spreadsheet_id, worksheet.title if worksheet else "None"
    )

@app.on_event("startup")
def on_startup():
    _init_gspread()

# =========================
# Helpers
# =========================
def _now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")

def _parse_created_at(v: str) -> datetime:
    """
    created_at 포맷: YYYY-MM-DD HH:MM (KST)
    파싱 실패 시 아주 과거로 처리
    """
    try:
        dt = datetime.strptime(v, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=KST)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=KST)

# =========================
# Models
# =========================
class Reservation(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM (24h)")
    party_size: int = Field(..., ge=1, le=50)
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=5, max_length=30)
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        datetime.strptime(v, "%H:%M")
        return v

class CancelRequest(BaseModel):
    # 식별 키 (최소)
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM (24h)")
    phone: str = Field(..., min_length=5, max_length=30)
    # 동명이인/중복 방지 보조(선택)
    name: Optional[str] = Field(default=None, max_length=100)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        datetime.strptime(v, "%H:%M")
        return v

class ApiResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    created_at: Optional[str] = None
    cancelled_at: Optional[str] = None

# =========================
# Endpoints (Health)
# =========================
@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    return "OK"

@app.api_route("/", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def root():
    return "OK"

@app.get("/health/sheets", response_model=ApiResponse)
def health_sheets():
    if worksheet is None:
        return ApiResponse(status="error", message="google sheet not initialized")
    return ApiResponse(status="ok", message=f"sheets ok: {worksheet.title}")

# =========================
# Reservation APIs
# =========================
@app.post("/reservation/create", response_model=ApiResponse)
def create_reservation(res: Reservation):
    if worksheet is None:
        raise HTTPException(status_code=500, detail="Google Sheet not initialized")

    created_at = _now_kst_str()
    status = "CONFIRMED"
    cancelled_at = ""

    logger.info(
        "Create reservation: date=%s time=%s party=%s name=%s phone=%s notes=%s",
        res.date, res.time, res.party_size, res.name, res.phone, (res.notes or "")
    )

    # ✅ 시트 컬럼 순서에 정확히 맞춤:
    # date, time, party_size, name, phone, notes, created_at, status, cancelled_at
    row = [
        res.date,
        res.time,
        res.party_size,
        res.name,
        res.phone,
        res.notes or "",
        created_at,
        status,
        cancelled_at,
    ]

    try:
        worksheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        logger.exception("Failed to append row to Google Sheet")
        raise HTTPException(status_code=502, detail="Failed to write to Google Sheet") from e

    return ApiResponse(status="ok", message="reservation created", created_at=created_at)

@app.post("/reservation/cancel", response_model=ApiResponse)
def cancel_reservation(req: CancelRequest):
    if worksheet is None:
        raise HTTPException(status_code=500, detail="Google Sheet not initialized")

    # 컬럼 인덱스(1-based for gspread update_cell)
    # 1 date, 2 time, 3 party_size, 4 name, 5 phone, 6 notes, 7 created_at, 8 status, 9 cancelled_at
    COL_DATE = 1
    COL_TIME = 2
    COL_NAME = 4
    COL_PHONE = 5
    COL_CREATED_AT = 7
    COL_STATUS = 8
    COL_CANCELLED_AT = 9

    try:
        values = worksheet.get_all_values()
    except Exception as e:
        logger.exception("Failed to read Google Sheet")
        raise HTTPException(status_code=502, detail="Failed to read Google Sheet") from e

    if not values or len(values) < 2:
        return ApiResponse(status="error", message="no reservation data")

    header = values[0]
    rows = values[1:]  # data only

    # 후보 찾기: phone+date+time 일치, status=CONFIRMED, (선택) name 일치
    candidates = []
    for idx0, r in enumerate(rows, start=2):  # 실제 sheet row index (header=1)
        # 안전하게 길이 보정
        r = r + [""] * (len(header) - len(r))

        date_v = r[COL_DATE - 1].strip()
        time_v = r[COL_TIME - 1].strip()
        name_v = r[COL_NAME - 1].strip()
        phone_v = r[COL_PHONE - 1].strip()
        created_at_v = r[COL_CREATED_AT - 1].strip()
        status_v = r[COL_STATUS - 1].strip().upper()

        if date_v != req.date:
            continue
        if time_v != req.time:
            continue
        if phone_v != req.phone:
            continue
        if req.name and req.name.strip() and name_v != req.name.strip():
            continue
        if status_v != "CONFIRMED":
            continue

        candidates.append((idx0, _parse_created_at(created_at_v), created_at_v))

    if not candidates:
        return ApiResponse(status="error", message="matching CONFIRMED reservation not found")

    # 가장 최근 created_at인 1건만 취소 (중복 방지)
    candidates.sort(key=lambda x: x[1], reverse=True)
    target_row, _, target_created_at = candidates[0]

    cancelled_at = _now_kst_str()

    try:
        worksheet.update_cell(target_row, COL_STATUS, "CANCELLED")
        worksheet.update_cell(target_row, COL_CANCELLED_AT, cancelled_at)
    except Exception as e:
        logger.exception("Failed to update Google Sheet for cancel")
        raise HTTPException(status_code=502, detail="Failed to update Google Sheet") from e

    logger.info("Cancelled reservation row=%s phone=%s date=%s time=%s", target_row, req.phone, req.date, req.time)
    return ApiResponse(status="ok", message="reservation cancelled", created_at=target_created_at, cancelled_at=cancelled_at)
