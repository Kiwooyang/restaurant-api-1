from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

import os
import json
import gspread
from google.oauth2.service_account import Credentials


# FastAPI 앱 생성
app = FastAPI()

# CORS 허용 (테스트/웹 클라이언트용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Google Sheet 설정 (단순/안정 버전) ----
# 👇 스코프: 시트 API만 사용
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Render 환경 변수에서 서비스키 불러오기
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_KEY"])

# 자격 증명 생성
creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES,
)

# gspread 클라이언트 생성
gc = gspread.authorize(creds)

# ⚠️ 네 시트의 ID (이미 알려준 값)
SPREADSHEET_ID = "1Mfl2gm4DNkwX_Ick8T5NLMKFXr6Nv0ShuerPwHsA-lE"

# ID로 시트 열기 (Drive 검색 안 함)
sh = gc.open_by_key(SPREADSHEET_ID)
worksheet = sh.sheet1
# -----------------------------------------


# 예약 데이터 모델
class Reservation(BaseModel):
    date: str          
    time: str          
    party_size: int    
    name: str          
    phone: str         
    notes: Optional[str] = None  


# 헬스 체크용 엔드포인트
@app.get("/")
def health_check():
    return {"status": "ok", "message": "restaurant api alive"}


# 예약 생성 엔드포인트
@app.post("/reservation/create")
def create_reservation(res: Reservation):
    created_at = datetime.now().isoformat()

    # 1) 서버 로그 출력
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

    # 3) 응답 반환
    return {
        "status": "ok",
        "message": "reservation created",
        "created_at": created_at,
    }
