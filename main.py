# main.py
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

PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO,
]
LABEL = {
    const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury", const.VENUS: "Venus",
    const.MARS: "Mars", const.JUPITER: "Jupiter", const.SATURN: "Saturn",
    const.URANUS: "Uranus", const.NEPTUNE: "Neptune", const.PLUTO: "Pluto",
}
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
         "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

# где лежат efems *.se1
EPHE_PATH = os.path.join(os.path.dirname(__file__), "ephe")
swe.set_ephe_path(EPHE_PATH)

# --------- входные данные ---------
class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="IANA zone (Europe/Kyiv) или 'UTC±HH:MM'")
    lat: float
    lng: float
    house_system: str = Field(default="P", description="Система домов: P=Placidus, K=Koch, W=Whole, R=Regiomontanus и т.д.")

# --------- утилиты времени/углов ---------
def to_dt(date_str: str, time_str: str, timezone: str) -> Datetime:
    dt_local = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    dt_utc = dt_local.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt_utc.strftime("%Y/%m/%d"), dt_utc.strftime("%H:%M"), "+00:00")

def to_dt_utc_py(date_str: str, time_str: str, timezone: str):
    """Python datetime (UTC) для Swiss Ephemeris"""
    dt_local = parser.parse(f"{date_str} {time_str}")
    tzinfo = tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    return dt_local.replace(tzinfo=tzinfo).astimezone(tz.UTC)

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

def ang_diff(a, b):
    # минимальная разница углов 0..180
    return abs((a - b + 180) % 360 - 180)

# мажорные аспекты
MAJOR_ASPECTS = [
    ("conjunction", 0,   8.0),
    ("sextile",     60,  4.0),
    ("square",      90,  6.0),
    ("trine",       120, 6.0),
    ("opposition",  180, 8.0),
]

# --------- расчёт домов через Swiss Ephemeris ---------
def houses_by_swe(date_str: str, time_str: str, timezone: str, lat: float, lng: float, hs: str):
    """Возвращает (cusps[12], angles: dict с ASC/MC)"""
    dt_utc = to_dt_utc_py(date_str, time_str, timezone)
    # дробные часы UTC
    h = dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600
    jd_ut = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, h, swe.GREG_CAL)

    # Swiss: bytes code системы домов
    hsys = (hs or "P").strip()[:1].upper().encode("ascii")
    cusps, ascmc = swe.houses(jd_ut, lat, lng, hsys)  # cusps: 1..12
    # ascmc: [ASC, MC, ARMC, Vertex, Equasc, Co-Asc W.Koch, Co-Asc Munkasey, Polar Asc]
    asc = float(ascmc[0]); mc = float(ascmc[1])

    # нормализуем 12 куспов в список 0..11
    houses = [round(float(x) % 360, 6) for x in cusps[:12]]
    angles = {
        "ASC": {"lon": round(asc % 360, 6), "sign": sign_from_lon(asc)},
        "MC":  {"lon": round(mc % 360,  6), "sign": sign_from_lon(mc)},
    }
    return houses, angles

def house_of(lon: float, cusps: list[float]) -> int | None:
    """Определяем номер дома 1..12 по долготе и массиву куспов (Placidus/и пр.)"""
    if not cusps or len(cusps) != 12:
        return None
    lon = lon % 360
    for i in range(12):
        c1 = cusps[i]
        c2 = cusps[(i + 1) % 12]
        if c1 <= c2:
            inside = (lon >= c1 and lon < c2)
        else:
            # переход через 360
            inside = (lon >= c1 or lon < c2)
        if inside:
            return i + 1
    return 12

# --------- эндпоинты ---------
@app.post("/chart")
def chart_endpoint(req: ChartRequest):
    # flatlib для планет
    dt = to_dt(req.date, req.time, req.timezone)
    lat_str = deg_to_dm_cardinal(req.lat, is_lat=True)
    lon_str = deg_to_dm_cardinal(req.lng, is_lat=False)
    pos = GeoPos(lat_str, lon_str)
    nc = chart.Chart(dt, pos, IDs=PLANETS)

    # позиции планет
    positions = {}
    for pid in PLANETS:
        obj = nc.get(pid)
        positions[LABEL[pid]] = {
            "lon": float(obj.lon),
            "lat": float(obj.lat),
            "sign": sign_from_lon(obj.lon),
            "house": None,  # заполним после расчёта домов
        }

    # дома + углы через Swiss Ephemeris
    try:
        houses, angles = houses_by_swe(req.date, req.time, req.timezone, req.lat, req.lng, req.house_system)
    except Exception as e:
        # если что-то пошло не так, отдаём только ASC/MC из flatlib
        angles = {
            "ASC": {"lon": round(nc.get(const.ASC).lon, 6), "sign": sign_from_lon(nc.get(const.ASC).lon)},
            "MC":  {"lon": round(nc.get(const.MC).lon,  6), "sign": sign_from_lon(nc.get(const.MC).lon)},
        }
        houses = []

    # подставим дом для каждой планеты (если есть куспы)
    if houses:
        for name, p in positions.items():
            p["house"] = house_of(p["lon"], houses)

    # аспекты (мажорные)
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
                        "applying": None,  # без скоростей не считаем
                    })
                    break

    return {
        "positions": positions,   # у каждой планеты: lon, lat, sign, house
        "angles": angles,         # ASC/MC
        "houses": houses,         # список из 12 куспов (в градусах)
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

from fastapi import Response
import math

def svg_aspects(positions: dict, aspects: list, size=420):
    cx = cy = size // 2
    r = size * 0.45

    # координаты планет по долготе
    def pol(lon_deg):
        ang = math.radians(90 - lon_deg)  # 0° = Овен на востоке; сдвиг под SVG
        return (cx + r * math.cos(ang), cy - r * math.sin(ang))

    # карта имён → долгота
    lons = {name: p["lon"] for name, p in positions.items()}

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">')
    parts.append(f'<rect width="100%" height="100%" fill="none"/>')

    # внешний круг
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#8a7a53" stroke-width="1.2"/>')

    # деления знаков
    for k in range(12):
        ang = math.radians(90 - k*30)
        x1 = cx + r * math.cos(ang)
        y1 = cy - r * math.sin(ang)
        x2 = cx + (r-8) * math.cos(ang)
        y2 = cy - (r-8) * math.sin(ang)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#8a7a53" stroke-width="1"/>')

    # аспекты (цвет по типу)
    colors = {"conjunction":"#d9b87a","sextile":"#6aa6ff","square":"#ff6b6b","trine":"#66d17e","opposition":"#ffa94d"}
    for asp in aspects:
        a, b = asp["a"], asp["b"]
        if a not in lons or b not in lons: 
            continue
        x1, y1 = pol(lons[a])
        x2, y2 = pol(lons[b])
        col = colors.get(asp["type"], "#ccc")
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-opacity="0.85" stroke-width="1.6"/>')

    # точки планет
    for name, lon in lons.items():
        x, y = pol(lon)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#d9b87a"/>')

    parts.append('</svg>')
    return ''.join(parts)

@app.post("/render/aspects")
def render_aspects(req: ChartRequest):
    data = chart_endpoint(req)  # переиспользуем расчёт
    svg = svg_aspects(data["positions"], data["aspects"])
    return Response(content=svg, media_type="image/svg+xml")
