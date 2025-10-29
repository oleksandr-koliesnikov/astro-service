from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dateutil import parser, tz
from flatlib import const, chart
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
import os
import math
import swisseph as swe

app = FastAPI(title="HoroscopeHub Astro Service")

# -------------------- Config --------------------
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
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
    "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

# Путь к эфемеридам Swiss Ephemeris
EPHE_PATH = os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

# Мажорные аспекты (название, угол, допуск)
MAJOR_ASPECTS = [
    ("conjunction", 0,   8.0),
    ("sextile",     60,  4.0),
    ("square",      90,  6.0),
    ("trine",       120, 6.0),
    ("opposition",  180, 8.0),
]

# -------------------- Models --------------------
class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="IANA zone (e.g. Europe/Kyiv) or 'UTC±HH:MM'")
    lat: float
    lng: float
    house_system: str | None = Field(default="P", description="Домовая система для Swiss Ephemeris (по умолчанию Placidus)")

# -------------------- Helpers --------------------
def sign_from_lon(lon: float) -> str:
    return SIGNS[int((lon % 360) // 30)]

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

def to_dt(date_str: str, time_str: str, timezone: str) -> tuple[Datetime, "datetime"]:
    """
    Возвращает:
      - flatlib.Datetime в UTC для построения карты,
      - python datetime (UTC) для расчётов Swiss Ephemeris.
    """
    from datetime import timezone as py_tz

    dt_local = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    dt_utc = dt_local.replace(tzinfo=tzinfo).astimezone(py_tz.utc)

    fl_dt = Datetime(dt_utc.strftime("%Y/%m/%d"), dt_utc.strftime("%H:%M"), "+00:00")
    return fl_dt, dt_utc

def julday_utc(dt_utc: "datetime") -> float:
    hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0 + dt_utc.microsecond / 3.6e9
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)

def houses_by_swe(dt_utc: "datetime", lat: float, lng: float, hsys: str = "P") -> tuple[list[float], dict]:
    """
    Возвращает:
      - список из 12 долготы домов (H1..H12),
      - углы ASC/MC (as dict) из Swiss Ephemeris.
    """
    jd = julday_utc(dt_utc)
    cusps, ascmc = swe.houses(jd, lat, lng, hsys.encode() if isinstance(hsys, str) else hsys)
    # cusps: 1..12; ascmc: 0=ASC, 1=MC
    houses = [round(float(cusps[i]), 6) for i in range(12)]
    angles = {
        "ASC": {"lon": round(float(ascmc[0]), 6), "sign": sign_from_lon(ascmc[0])},
        "MC":  {"lon": round(float(ascmc[1]), 6), "sign": sign_from_lon(ascmc[1])},
    }
    return houses, angles

def ang_diff(a: float, b: float) -> float:
    """Минимальная разница углов 0..180"""
    return abs((a - b + 180) % 360 - 180)

# -------------------- Endpoints --------------------
@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    # Время/координаты
    fl_dt, dt_utc = to_dt(req.date, req.time, req.timezone)
    lat_str = deg_to_dm_cardinal(req.lat, is_lat=True)
    lon_str = deg_to_dm_cardinal(req.lng, is_lat=False)
    pos = GeoPos(lat_str, lon_str)

    # Положение планет (flatlib)
    nc = chart.Chart(fl_dt, pos, IDs=PLANETS)
    positions: dict[str, dict] = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        positions[LABEL[pid]] = {
            "lon": float(obj.lon),
            "sign": sign_from_lon(obj.lon),
            "lat": float(obj.lat),
        }

    # --- ДОМА (Flatlib 0.2.3 совместимо) ---
houses = []
try:
    house_data = getattr(nc, "houses", None)
    if hasattr(house_data, "houses"):
        # flatlib 0.2.3 формат
        for h in house_data.houses:
            lon = getattr(h, "lon", None)
            if lon is not None:
                houses.append({
                    "num": len(houses) + 1,
                    "lon": round(lon, 6),
                    "sign": sign_from_lon(lon)
                })
            elif hasattr(h, "cusp") and hasattr(h.cusp, "lon"):
                houses.append({
                    "num": len(houses) + 1,
                    "lon": round(h.cusp.lon, 6),
                    "sign": sign_from_lon(h.cusp.lon)
                })
    else:
        # fallback — если структура другая
        for i in range(1, 13):
            cusp = nc.getHouse(i)
            houses.append({
                "num": i,
                "lon": round(cusp.lon, 6),
                "sign": sign_from_lon(cusp.lon)
            })
except Exception as e:
    houses = [{"error": str(e)}]

# --- УГЛЫ ---
angles = {
    "ASC": {"lon": round(nc.get(const.ASC).lon, 6), "sign": sign_from_lon(nc.get(const.ASC).lon)},
    "MC":  {"lon": round(nc.get(const.MC).lon, 6), "sign": sign_from_lon(nc.get(const.MC).lon)}
}

    # Мажорные аспекты (без скоростей; applying=None)
    asps = []
    objs = [nc.get(pid) for pid in PLANETS]
    for i in range(len(objs)):
        for j in range(i + 1, len(objs)):
            d = ang_diff(objs[i].lon, objs[j].lon)
            for name, target, orb in MAJOR_ASPECTS:
                delta = abs(d - target)
                if delta <= orb:
                    asps.append({
                        "a": LABEL[objs[i].id],
                        "b": LABEL[objs[j].id],
                        "type": name,
                        "orb": round(delta, 2),
                        "applying": None
                    })
                    break

    return {
        "positions": positions,
        "angles": angles,
        "houses": houses,     # [] если время некорректно/нет эфемерид
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
