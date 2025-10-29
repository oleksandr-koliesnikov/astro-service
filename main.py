from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dateutil import parser, tz
from flatlib import const, chart, aspects
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
import os
import swisseph as swe

app = FastAPI(title="HoroscopeHub Astro Service")

PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO
]
LABEL = {
    const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury", const.VENUS: "Venus",
    const.MARS: "Mars", const.JUPITER: "Jupiter", const.SATURN: "Saturn",
    const.URANUS: "Uranus", const.NEPTUNE: "Neptune", const.PLUTO: "Pluto"
}
SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
    "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

EPHE_PATH = os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="IANA zone (e.g. Europe/Kyiv) or 'UTC±HH:MM'")
    lat: float
    lng: float

def to_dt(date_str: str, time_str: str, timezone: str) -> Datetime:
    # принимает "Europe/Kyiv" ИЛИ "UTC-04:00"
    dt_local = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    dt_utc = dt_local.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt_utc.strftime("%Y/%m/%d"), dt_utc.strftime("%H:%M"), "+00:00")

def deg_to_dm_cardinal(value: float, is_lat: bool) -> str:
    hemi_pos = 'n' if is_lat else 'e'
    hemi_neg = 's' if is_lat else 'w'
    hemi = hemi_pos if value >= 0 else hemi_neg
    v = abs(value)
    d = int(v)
    m = int(round((v - d) * 60))
    if m == 60:
        d += 1
        m = 0
    return (f"{d:02d}{hemi}{m:02d}" if is_lat else f"{d:03d}{hemi}{m:02d}")

def sign_from_lon(lon: float) -> str:
    return SIGNS[int((lon % 360) // 30)]

@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    dt = to_dt(req.date, req.time, req.timezone)
    lat_str = deg_to_dm_cardinal(req.lat, is_lat=True)
    lon_str = deg_to_dm_cardinal(req.lng, is_lat=False)
    pos = GeoPos(lat_str, lon_str)

    nc = chart.Chart(dt, pos, IDs=PLANETS)

    # Позиции планет
    positions = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        positions[LABEL[pid]] = {
            "lon": obj.lon,
            "sign": sign_from_lon(obj.lon),
            "lat": obj.lat,
        }

    # Углы
    angles = {
        "ASC": {"lon": round(nc.get(const.ASC).lon, 6), "sign": sign_from_lon(nc.get(const.ASC).lon)},
        "MC":  {"lon": round(nc.get(const.MC).lon,  6), "sign": sign_from_lon(nc.get(const.MC).lon)},
    }

    # Дома (совместимо с flatlib 0.2.3)
    houses = []
    try:
        # В 0.2.3 у Chart.houses есть .houses (список объектов House)
        for h in getattr(nc.houses, "houses", []):
            lon = getattr(h, "lon", None)
            if lon is not None:
                houses.append(round(lon, 6))
            elif hasattr(h, "cusp") and hasattr(h.cusp, "lon"):
                houses.append(round(h.cusp.lon, 6))
    except Exception:
        houses = []

    # Аспекты (major по умолчанию)
    objs = [nc.get(pid) for pid in PLANETS]
    found = aspects.getAspects(objs, aspects.MAJOR_ASPECTS)  # разом для всех пар
    asps = []
    for asp in found:
        asps.append({
            "a": LABEL[getattr(asp, "obj1").id],
            "b": LABEL[getattr(asp, "obj2").id],
            "type": asp.type,
            "orb": round(getattr(asp, "orb", 0.0), 2),
            "applying": getattr(asp, "applying", getattr(asp, "isApplying", False)),
        })

    return {"positions": positions, "angles": angles, "houses": houses, "aspects": asps}

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
