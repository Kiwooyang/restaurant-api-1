import os
import json
import logging
from typing import Optional, Literal

import gspread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
app = FastAPI(title="Restaurant Reservation API", version="1.0.0")

# =========================
# CORS (환경변수로 제어)
# - 기본은 전체 허용(기존 동작 유지)
# - 운영에서는 CORS_ALLOW_ORIGINS를 콤마로 지정 권장
# =========================
cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins = ["*"] if cors_origins.strip() == "*" else [o.strip() for o in cors_origins.split(",") if o.strip()]

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

# 필수 환경변수
ENV_GOOGLE_KEY = "GOOGLE_SERVICE_KEY"
ENV_SHEET_ID = "SPREADSHEET_ID"  # 기존 하드코딩 제거
ENV_WORKSHEET = "WORKSHEET_NAME"  # 선택(기본: 첫번째 시트)

gc: Optional[gspread.Client] = None
worksheet = None


def _get_env(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def _init_gspread() -> None:
    """
    Render/운영 환경에서 안정적으로 초기화하기 위해 startup에서 1회만 수행.
    """
    global gc, worksheet

    # 1) env 로딩
    raw_key = _get_env(ENV_GOOGLE_KEY, required=True)
    spreadsheet_id = _get_env(ENV_SHEET_ID, required=True)
    worksheet_name = _get_env(ENV_WORKSHEET, required=False, default="")

    # 2) 서비스 계정 JSON 파싱
    try:
        service_account_info = json.loads(raw_key)
    except Exception as e:
        # 흔한 실수: 따옴표/escape 깨짐
        raise RuntimeError(
            f"{ENV_GOOGLE_KEY} is not valid JSON. Ensure it is a JSON string in env."
        ) from e

    # 3) creds / gspread
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # 4) Spreadsheet open
    sh = gc.open_by_key(spreadsheet_id)

    # 5) Worksheet 선택
    if worksheet_name.strip():
        worksheet = sh.worksheet(worksheet_name.strip())
    else:
        worksheet = sh.sheet1

    logger.info("Google Sheets initialized. spreadsheet_id=%s worksheet=%s",
                spreadsheet_id,
                worksheet.title if worksheet else "None")


@app.on_event("startup")
def on_startup():
    try:
        _init_gspread()
    except Exception as e:
        # 초기화 실패는 서비스 전체 장애로 보는 편이 일반적
        logger.exception("Startup failed: cannot initialize Google Sheets.")
        raise


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
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format")
        return v

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%H:%M")
        except ValueError:
            raise ValueError("time must be in HH:MM (24h) format")
        return v


class ApiResponse(BaseModel):
    status: Literal["ok", "error"]
    message: str
    created_at: Optional[str] = None


# =========================
# Endpoints
# =========================
@app.get("/health", response_model=ApiResponse)
def health():
    # Sheets가 초기화되었는지까지 같이 체크
    if worksheet is None:
        return ApiResponse(status="error", message="google sheet not initialized")
    return ApiResponse(status="ok", message="alive")


@app.get("/", response_model=ApiResponse)
def root():
    # 기존 "/" health_check와 중복이어서 명확히 분리
    return ApiResponse(status="ok", message="restaurant api alive")


@app.post("/reservation/create", response_model=ApiResponse)
def create_reservation(res: Reservation):
    if worksheet is None:
        logger.error("Worksheet not initialized")
        raise HTTPException(status_code=500, detail="Google Sheet not initialized")

    created_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    # 서버 로그 (민감정보 최소화)
    logger.info(
        "New reservation: date=%s time=%s party=%s name=%s phone=%s",
        res.date, res.time, res.party_size, res.name, res.phone
    )

    row = [
        res.date,
        res.time,
        res.party_size,
        res.name,
        res.phone,
        res.notes or "",
        created_at,
    ]

    try:
        worksheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        logger.exception("Failed to append row to Google Sheet")
        raise HTTPException(status_code=502, detail="Failed to write to Google Sheet") from e

    return ApiResponse(status="ok", message="reservation created", created_at=created_at)
