# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dateutil import parser, tz
from flatlib import const, chart, aspects
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
import os
import swisseph as swe

app = FastAPI(title="HoroscopeHub Astro Service", version="1.0.0")

# --------------------------
# Константы и маппинги
# --------------------------
PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO,
]
LABEL = {
    const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury", const.VENUS: "Venus",
    const.MARS: "Mars", const.JUPITER: "Jupiter", const.SATURN: "Saturn",
    const.URANUS: "Uranus", const.NEPTUNE: "Neptune", const.PLUTO: "Pluto",
}
SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]
# flatlib → Swiss Ephemeris IDs
SWE_MAP = {
    const.SUN: swe.SUN,
    const.MOON: swe.MOON,
    const.MERCURY: swe.MERCURY,
    const.VENUS: swe.VENUS,
    const.MARS: swe.MARS,
    const.JUPITER: swe.JUPITER,
    const.SATURN: swe.SATURN,
    const.URANUS: swe.URANUS,
    const.NEPTUNE: swe.NEPTUNE,
    const.PLUTO: swe.PLUTO,
}

# --------------------------
# Эфемериды
# --------------------------
# Можно переопределить через переменную окружения EPHE_PATH
EPHE_PATH = os.getenv("EPHE_PATH") or os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

# --------------------------
# Модели запросов
# --------------------------
class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="e.g. Europe/Kyiv")
    lat: float  # +N / -S (десятичные градусы)
    lng: float  # +E / -W (десятичные градусы)

# --------------------------
# Утилиты
# --------------------------
def to_dt(date_str: str, time_str: str, timezone: str) -> Datetime:
    """В локальном пояса -> UTC -> flatlib.Datetime(+00:00)."""
    try:
        dt = parser.parse(f"{date_str} {time_str}")
    except Exception:
        raise HTTPException(400, "Invalid date/time format, use YYYY-MM-DD and HH:MM")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(400, "Invalid timezone")
    dt = dt.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt.strftime("%Y/%m/%d"), dt.strftime("%H:%M"), "+00:00")

def deg_to_dm_cardinal(value: float, is_lat: bool) -> str:
    """Десятичные градусы -> формат GeoPos: DDnMM / DDD eMM и т.п."""
    hemi_pos = 'n' if is_lat else 'e'
    hemi_neg = 's' if is_lat else 'w'
    hemi = hemi_pos if value >= 0 else hemi_neg
    v = abs(value)
    d = int(v)
    m = int(round((v - d) * 60))
    if m == 60:
        d += 1
        m = 0
    return (f"{d:02d}{hemi}{m:02d}") if is_lat else (f"{d:03d}{hemi}{m:02d}")

def sign_from_lon(lon: float) -> str:
    return SIGNS[int((lon % 360) // 30)]

# --------------------------
# Эндпоинты
# --------------------------
@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    # 1) Дата/время и позиция
    dt = to_dt(req.date, req.time, req.timezone)
    lat_str = deg_to_dm_cardinal(req.lat, is_lat=True)
    lon_str = deg_to_dm_cardinal(req.lng, is_lat=False)
    pos = GeoPos(lat_str, lon_str)

    # 2) Карта (flatlib)
    nc = chart.Chart(dt, pos, IDs=PLANETS)

    # 3) Юлианская дата для вычисления скоростей в Swiss Ephemeris
    # исправленное
    y, m, d = map(int, dt.date.split('/'))
    hh, mm = map(int, dt.time.split(':'))
    ut = hh + mm / 60.0
    jd = swe.julday(y, m, d, ut, swe.GREG_CAL)

    # 4) Позиции планет (+ скорость долготы в град/сутки)
    positions = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        # lon, lat, dist, lon_spd, lat_spd, dist_spd
        lon, lat, dist, lon_spd, lat_spd, dist_spd = swe.calc_ut(
            jd, SWE_MAP[pid], swe.FLG_SWIEPH | swe.FLG_SPEED
        )
        positions[LABEL[pid]] = {
            "lon": round(obj.lon, 6),
            "lat": round(obj.lat, 6),
            "sign": sign_from_lon(obj.lon),
            "speed": round(lon_spd, 6),  # скорость долготы
        }

    # 5) Углы (ASC, MC)
    asc_lon = nc.get(const.ASC).lon
    mc_lon = nc.get(const.MC).lon
    angles = {
        "ASC": {"lon": round(asc_lon, 6), "sign": sign_from_lon(asc_lon)},
        "MC":  {"lon": round(mc_lon, 6),  "sign": sign_from_lon(mc_lon)},
    }

    # 6) Дома (куспиды)
    houses = [round(hc.lon, 6) for hc in nc.houses.cusps]

    # 7) Аспекты между планетами
    asps = []
    objs = [nc.get(pid) for pid in PLANETS]
    n = len(objs)
    for i in range(n):
        for j in range(i + 1, n):
            asp = aspects.getAspect(objs[i], objs[j])
            if asp:
                asps.append({
                    "a": LABEL[objs[i].id],
                    "b": LABEL[objs[j].id],
                    "type": asp.type,          # conj, opp, trine, square, sextile...
                    "orb": round(asp.orb, 2),  # орбис
                    "applying": asp.applying,  # сходящийся/расходящийся
                })

    return {
        "positions": positions,
        "angles": angles,
        "houses": houses,
        "aspects": asps,
    }

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    try:
        _ = os.listdir(EPHE_PATH)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
