from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dateutil import parser, tz
from flatlib import const, chart, aspects
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
import math

app = FastAPI(title="HoroscopeHub Astro Service")

PLANETS = [const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
           const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO]
LABEL = {
    const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury", const.VENUS: "Venus",
    const.MARS: "Mars", const.JUPITER: "Jupiter", const.SATURN: "Saturn",
    const.URANUS: "Uranus", const.NEPTUNE: "Neptune", const.PLUTO: "Pluto"
}
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
         "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

class ChartRequest(BaseModel):
    name: str = "Client"
    date: str = Field(..., description="YYYY-MM-DD")
    time: str = Field(..., description="HH:MM")
    timezone: str = Field(..., description="e.g. America/Toronto")
    lat: float
    lng: float

def to_dt(date_str,time_str,timezone):
    dt=parser.parse(f"{date_str} {time_str}")
    tzinfo=tz.gettz(timezone)
    if tzinfo is None:
        raise HTTPException(400,"Invalid timezone")
    dt=dt.replace(tzinfo=tzinfo).astimezone(tz.UTC)
    return Datetime(dt.strftime("%Y/%m/%d"),dt.strftime("%H:%M"),"+00:00")

@app.post("/chart")
def chart_endpoint(req:ChartRequest):
    dt=to_dt(req.date,req.time,req.timezone)
    pos=GeoPos(str(req.lat),str(req.lng))
    nc=chart.Chart(dt,pos,IDs=PLANETS)

    positions={}
    for pid in PLANETS:
        obj=nc.get(pid)
        sign=SIGNS[int((obj.lon%360)//30)]
        positions[LABEL[pid]]={"lon":obj.lon,"sign":sign}

    return {"positions":positions}
@app.get("/")
def root():
    # простой ответ для healthcheck
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"ok": True}
