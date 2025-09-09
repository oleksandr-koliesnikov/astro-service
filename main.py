from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dateutil import parser, tz
from flatlib import const, chart
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
import swisseph as swe
import os

app = FastAPI(title="HoroscopeHub Astro Service")

# ---------- Swiss Ephemeris ----------
# Папка с эфемеридами (ты уже залил её как /ephe в репозитории)
EPHE_PATH = os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

# ---------- Константы ----------
PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO
]
LABEL = {
    const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury", const.VENUS: "Venus",
    const.MARS: "Mars", const.JUPITER: "Jupiter", const.SATURN: "Saturn",
    const.URANUS: "Uranus", const.NEPTUNE: "Neptune", const.PLUTO: "Pluto",
}
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# ---------- Модель запроса ----------
class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="e.g. America/Toronto")
    lat: float
    lng: float

# ---------- Вспомогательные функции ----------
def to_dt(date_str: str, time_str: str, timezone: str) -> Datetime:
    dt = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    dt = dt.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt.strftime("%Y/%m/%d"), dt.strftime("%H:%M"), "+00:00")

def sign_from_lon(lon: float) -> str:
    """Возвращает знак зодиака по долготе (0..360)."""
    idx = int((lon % 360) // 30)  # 0..11
    return SIGNS[idx]

# ---------- Эндпоинты ----------
@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    # Время/дата в UTC для flatlib
    dt = to_dt(req.date, req.time, req.timezone)

    # В flatlib широта/долгота передаются строками
    pos = GeoPos(str(req.lat), str(req.lng))

    # Строим натальную карту (по умолчанию houses=Placidus в flatlib)
    nc = chart.Chart(dt, pos, IDs=PLANETS)

    positions = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        positions[LABEL[pid]] = {
            "lon": obj.lon,     # гео. долгота, градусы
            "lat": obj.lat,     # гео. широта планеты (не широта места)
            "sign": sign_from_lon(obj.lon),
        }

    return {"positions": positions}

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    # Простая проверка, что Swiss Ephemeris видит файлы
    try:
        _ = os.listdir(EPHE_PATH)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
