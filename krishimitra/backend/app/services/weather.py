"""Weather adapter (Open-Meteo, no API key). Cached per ~1 km grid cell so 10k users do not mean 10k upstream calls."""
import logging
import time

import httpx

from app.core.config import get_settings

log = logging.getLogger("weather")
_cache: dict[tuple[float, float], tuple[float, dict]] = {}
URL = "https://api.open-meteo.com/v1/forecast"
CODES = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog", 51: "Light drizzle", 53: "Drizzle",
         55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain", 80: "Showers", 81: "Showers", 82: "Heavy showers",
         95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def get_weather(lat: float, lon: float) -> dict | None:
    s = get_settings()
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < s.weather_cache_seconds:
        return hit[1]
    try:
        r = httpx.get(URL, timeout=6, params={
            "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 5,
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code"})
        r.raise_for_status()
        j = r.json()
    except Exception as e:  # network / upstream failure: serve stale data if we have it, else None
        log.warning("weather fetch failed: %s", e)
        return hit[1] if hit else None
    c, d = j.get("current", {}), j.get("daily", {})
    out = {"current": {"temp_c": c.get("temperature_2m"), "humidity": c.get("relative_humidity_2m"), "rain_mm": c.get("precipitation"),
                       "wind_kmh": c.get("wind_speed_10m"), "summary": CODES.get(c.get("weather_code"), "")},
           "daily": [{"date": d["time"][i], "max_c": d["temperature_2m_max"][i], "min_c": d["temperature_2m_min"][i],
                      "rain_mm": d["precipitation_sum"][i], "rain_prob": (d.get("precipitation_probability_max") or [None] * 9)[i],
                      "summary": CODES.get(d["weather_code"][i], "")} for i in range(len(d.get("time", [])))],
           "source": "Open-Meteo", "fetched_at": int(time.time())}
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = (time.time(), out)
    return out


def weather_alerts(w: dict | None) -> list[dict]:
    """Plain thresholds on the forecast. These are generic alerts, not agronomic guarantees."""
    if not w:
        return []
    out = []
    for day in w["daily"][:3]:
        if (day["rain_mm"] or 0) >= 40:
            out.append({"kind": "HEAVY_RAIN", "date": day["date"], "text": f"Heavy rain expected ({day['rain_mm']} mm). Check drainage; avoid spraying."})
        elif (day["rain_prob"] or 0) >= 70 and (day["rain_mm"] or 0) >= 5:
            out.append({"kind": "RAIN", "date": day["date"], "text": "Rain likely. Postpone irrigation and spraying."})
        if (day["max_c"] or 0) >= 40:
            out.append({"kind": "HEAT", "date": day["date"], "text": f"Very hot day ({day['max_c']}°C). Irrigate in the evening."})
        if day["min_c"] is not None and day["min_c"] <= 4:
            out.append({"kind": "COLD", "date": day["date"], "text": f"Cold night ({day['min_c']}°C). Frost risk for sensitive crops."})
    return out
