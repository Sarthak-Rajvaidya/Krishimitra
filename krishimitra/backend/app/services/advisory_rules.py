"""Transparent rule-based advisory. Every output lists the inputs and rule that produced it.
Reference ranges come from the editable CropKnowledge table and are generic - always confirm locally."""
from datetime import date

DISCLAIMER = "Generic guidance from reference ranges. Confirm with your local agriculture officer or a KrishiMitra expert before acting."


def growth_stage(stages: list | None, sowing: date | None, duration: int | None, today: date | None = None) -> str | None:
    if not (stages and sowing and duration):
        return None
    pct = max(0, (( today or date.today()) - sowing).days) / duration * 100
    for st in stages:
        if pct <= st["until_pct"]:
            return st["name"]
    return "Maturity"


def crop_suitability(k, ph: float | None, soil_type: str | None, season: str | None) -> dict:
    reasons, score = [], 0
    if season and season.upper() in k.seasons.split(","):
        score += 1
        reasons.append(f"Grown in {season.upper().title()} season")
    elif season:
        reasons.append(f"Usually not a {season.title()} crop")
    if ph is not None and k.ph_min is not None and k.ph_max is not None:
        if k.ph_min <= ph <= k.ph_max:
            score += 1
            reasons.append(f"Soil pH {ph} is within {k.ph_min}-{k.ph_max}")
        else:
            reasons.append(f"Soil pH {ph} is outside {k.ph_min}-{k.ph_max}")
    if soil_type and soil_type.lower() in k.soil_types.lower():
        score += 1
        reasons.append(f"{soil_type.title()} soil suits this crop")
    return {"crop": k.crop, "score": score, "reasons": reasons, "water_need": k.water_need, "duration_days": k.duration_days}


def soil_findings(s) -> list[dict]:
    """Interpret a SoilReading against generic ranges. Fertiliser quantities are deliberately NOT given."""
    out = []
    if s.ph is not None:
        if s.ph < 5.5:
            out.append({"item": "pH", "level": "LOW", "text": "Strongly acidic. Ask an expert about liming for your crop."})
        elif s.ph > 8.5:
            out.append({"item": "pH", "level": "HIGH", "text": "Strongly alkaline. Ask an expert about gypsum or organic matter."})
        else:
            out.append({"item": "pH", "level": "OK", "text": "pH is in a workable range for most crops."})
    for name, v, lo, hi in (("Nitrogen", s.nitrogen, 280, 560), ("Phosphorus", s.phosphorus, 11, 25), ("Potassium", s.potassium, 110, 280)):
        if v is not None:
            lvl = "LOW" if v < lo else "HIGH" if v > hi else "MEDIUM"
            out.append({"item": name, "level": lvl, "text": f"{name} is {lvl.lower()} (typical medium range {lo}-{hi} kg/ha). Fertiliser plan should come from your soil test report and an expert."})
    if s.organic_carbon is not None:
        lvl = "LOW" if s.organic_carbon < 0.5 else "HIGH" if s.organic_carbon > 0.75 else "MEDIUM"
        out.append({"item": "Organic carbon", "level": lvl, "text": "Add compost or farmyard manure to raise organic carbon." if lvl == "LOW" else "Organic carbon is adequate."})
    if s.ec is not None and s.ec > 2:
        out.append({"item": "Salinity (EC)", "level": "HIGH", "text": "Salinity is high. Consider salt-tolerant crops and better drainage."})
    return out


def irrigation_advice(k, moisture: float | None, rain_mm_next3: float, temp_max: float | None) -> dict:
    inputs = {"moisture_pct": moisture, "rain_next_3_days_mm": rain_mm_next3, "max_temp_c": temp_max}
    if k is None or moisture is None:
        return {"action": "UNKNOWN", "reason": "Need a soil moisture reading and crop reference data.", "inputs": inputs}
    if rain_mm_next3 >= 10:
        return {"action": "WAIT", "reason": f"About {rain_mm_next3:.0f} mm of rain is forecast in 3 days.", "inputs": inputs}
    if k.moisture_low is not None and moisture < k.moisture_low:
        return {"action": "IRRIGATE", "reason": f"Moisture {moisture:.0f}% is below {k.moisture_low:.0f}% for {k.crop}.", "inputs": inputs}
    return {"action": "OK", "reason": "Moisture is adequate.", "inputs": inputs}
