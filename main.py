from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

import os
import json
import gspread
from google.oauth2.service_account import Credentials



app = FastAPI()

# CORS 허용 (테스트 용도, 전체 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 나중에 원하면 특정 도메인만 넣을 수 있음
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Google Sheet 설정 ----
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Render 환경 변수에서 서비스키 불러오기
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_KEY"])

creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES,
)

gc = gspread.authorize(creds)

SPREADSHEET_NAME = "Restaurant_Reservations"  # 여기 시트 이름만 네 것으로 변경!
sh = gc.open(SPREADSHEET_NAME)
worksheet = sh.sheet1


class Reservation(BaseModel):
    date: str          # "2025-11-25"
    time: str          # "19:00"
    party_size: int    # 인원 수
    name: str          # 예약자 이름
    phone: str         # 연락처
    notes: Optional[str] = None  # 요청사항 (없으면 빈값)


@app.get("/")
def health_check():
    return {"status": "ok", "message": "restaurant api alive"}


@app.post("/reservation/create")
def create_reservation(res: Reservation):
    # 생성 시간
    created_at = datetime.now().isoformat()

    # 1) 서버 로그 찍기
    print("---- New Reservation ----")
    print("Date      :", res.date)
    print("Time      :", res.time)
    print("Party     :", res.party_size)
    print("Name      :", res.name)
    print("Phone     :", res.phone)
    print("Notes     :", res.notes)
    print("CreatedAt :", created_at)
    print("-------------------------")

    # 2) Google Sheet에 한 줄 추가
    row = [
        res.date,
        res.time,
        res.party_size,
        res.name,
        res.phone,
        res.notes or "",
        created_at,
    ]
    worksheet.append_row(row, value_input_option="USER_ENTERED")

    # 3) 클라이언트로 응답
    return {
        "status": "ok",
        "message": "reservation created",
        "created_at": created_at,
    }
