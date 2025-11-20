from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


app = FastAPI()

# CORS 허용 (테스트 용도, 전체 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 나중에 원하면 특정 도메인만 넣을 수 있음
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # 일단 1단계: 서버 로그(콘솔)에만 찍기
    print("---- New Reservation ----")
    print("Date      :", res.date)
    print("Time      :", res.time)
    print("Party     :", res.party_size)
    print("Name      :", res.name)
    print("Phone     :", res.phone)
    print("Notes     :", res.notes)
    print("CreatedAt :", datetime.now().isoformat())
    print("-------------------------")

    # 나중에 여기다가 Google Sheet에 쓰는 로직을 추가할 거야.

    return {
        "status": "ok",
        "message": "reservation created",
        "created_at": datetime.now().isoformat()
    }
