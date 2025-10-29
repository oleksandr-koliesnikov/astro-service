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
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
         "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

EPHE_PATH = os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="e.g. Europe/Kyiv")
    lat: float
    lng: float

def to_dt(date_str: str, time_str: str, timezone: str) -> Datetime:
    dt = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(400, "Invalid timezone")
    dt = dt.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt.strftime("%Y/%m/%d"), dt.strftime("%H:%M"), "+00:00")

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
    if is_lat:
        return f"{d:02d}{hemi}{m:02d}"
    else:
        return f"{d:03d}{hemi}{m:02d}"

def sign_from_lon(lon: float) -> str:
    return SIGNS[int((lon % 360) // 30)]

@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    dt = to_dt(req.date, req.time, req.timezone)
    lat_str = deg_to_dm_cardinal(req.lat, is_lat=True)
    lon_str = deg_to_dm_cardinal(req.lng, is_lat=False)
    pos = GeoPos(lat_str, lon_str)

    nc = chart.Chart(dt, pos, IDs=PLANETS)

    # --- Позиции планет ---
    positions = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        positions[LABEL[pid]] = {
            "lon": obj.lon,
            "sign": sign_from_lon(obj.lon),
            "lat": obj.lat
        }

    # --- Углы ---
    asc_lon = nc.get(const.ASC).lon
    mc_lon  = nc.get(const.MC).lon
    angles = {
        "ASC": {"lon": round(asc_lon, 6), "sign": sign_from_lon(asc_lon)},
        "MC":  {"lon": round(mc_lon,  6), "sign": sign_from_lon(mc_lon)}
    }

    # --- Дома (совместимо с flatlib 0.2.3) ---
    try:
        houses = [round(h.cusp.lon, 6) for h in nc.houses]   # новый интерфейс
    except Exception:
        try:
            houses = [round(h.lon, 6) for h in nc.houses.cusps]  # старый интерфейс
        except Exception:
            houses = []

    # --- Аспекты (требует список аспектов в 0.2.3) ---
    asps = []
    objs = [nc.get(pid) for pid in PLANETS]
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            asp = aspects.getAspect(objs[i], objs[j], aspects.MAJOR_ASPECTS)
            if asp:
                asps.append({
                    "a": LABEL[objs[i].id],
                    "b": LABEL[objs[j].id],
                    "type": asp.type,
                    "orb": round(asp.orb, 2),
                    "applying": asp.applying
                })

    return {
        "positions": positions,
        "angles": angles,
        "houses": houses,
        "aspects": asps
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
