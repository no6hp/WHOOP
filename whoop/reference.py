"""Compare personal values against published reference ranges.

All ranges are population guidance, not diagnoses. Sources are named in
REFERENCES so Claude can explain where a judgement comes from.
Age/sex are not exposed by the WHOOP API; set WHOOP_BIRTH_YEAR and
WHOOP_SEX (m/f) as environment variables to get age-specific comparisons.
"""

import os
import statistics
from datetime import datetime, timedelta, timezone

REFERENCES = {
    "rhr": "AHA: Ruhepuls 60–100 normal; Ausdauertrainierte oft 40–60. Kohortenstudien (z. B. Zhang 2016, CMAJ): "
           "jedes +10 bpm über ~60 geht mit höherem Gesamtsterberisiko einher.",
    "hrv": "Nächtliche RMSSD ist stark individuell und altersabhängig; Altersband-Werte sind grobe Mediane aus "
           "Wearable-Populationsdaten (Orientierung, kein Grenzwert). Entscheidend ist der eigene Trend.",
    "sleep": "AASM/SRS (2015) & National Sleep Foundation: Erwachsene 18–64 J. 7–9 h, ab 65 J. 7–8 h; "
             "<7 h regelmäßig ist mit erhöhtem Gesundheitsrisiko assoziiert.",
    "eff": "Schlafmedizin: Schlafeffizienz ≥85 % gilt als normal.",
    "stages": "Polysomnographie-Normwerte Erwachsene: Tiefschlaf (N3) ca. 13–23 % (sinkt mit Alter), REM ca. 20–25 %. "
              "Wearables schätzen Phasen nur näherungsweise.",
    "resp": "Normale Atemfrequenz Erwachsener in Ruhe/Schlaf: 12–20 /min.",
    "spo2": "SpO₂ ≥95 % normal; 90–94 % grenzwertig (Wearables messen ungenauer); wiederholt <90 % ärztlich abklären.",
    "activity": "WHO (2020): pro Woche 150–300 min moderate ODER 75–150 min intensive Ausdaueraktivität "
                "(1 min intensiv ≈ 2 min moderat), plus ≥2× Krafttraining.",
    "bmi": "WHO: BMI 18,5–24,9 Normalgewicht (bei viel Muskelmasse eingeschränkt aussagekräftig).",
    "hrmax": "Tanaka-Formel: HFmax ≈ 208 − 0,7 × Alter.",
}

# Rough medians of nightly RMSSD (ms) by age band for wearable users.
HRV_AGE_MEDIAN = [(25, 65), (35, 52), (45, 41), (55, 33), (65, 28), (200, 25)]


def _age() -> int | None:
    by = os.environ.get("WHOOP_BIRTH_YEAR")
    return datetime.now().year - int(by) if by and by.isdigit() else None


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def _rate(label: str, verdict: str, detail: str) -> str:
    return f"- **{label}:** {detail} → {verdict}"


def rhr_verdict(v: float) -> str:
    if v < 50:
        return "sehr niedrig – typisch für Ausdauertrainierte ✅ (ohne Beschwerden unbedenklich)"
    if v < 60:
        return "sehr gut ✅"
    if v < 70:
        return "gut / Normalbereich"
    if v < 80:
        return "Normalbereich, aber eher erhöht – Ausdauertraining senkt ihn"
    return "erhöht ⚠️ – Trend beobachten; dauerhaft >80 ärztlich ansprechen"


def section(days, i: int, db: dict, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    rows = days.rows[max(0, i - 29):i + 1]
    age = _age()
    L = ["## Einordnung nach Fachstandards (Ø 30 Tage)"]
    if age is None:
        L.append("_Alter unbekannt (WHOOP_BIRTH_YEAR nicht gesetzt) – altersabhängige Vergleiche nur grob._")

    rhr = _mean(r["rhr"] for r in rows)
    if rhr is not None:
        L.append(_rate("Ruhepuls", rhr_verdict(rhr), f"{rhr:.0f} bpm"))

    hrv = _mean(r["hrv"] for r in rows)
    if hrv is not None:
        if age is not None:
            med = next(m for a, m in HRV_AGE_MEDIAN if age < a)
            ratio = hrv / med
            v = ("deutlich über Altersmedian ✅" if ratio >= 1.25 else
                 "um den Altersmedian" if ratio >= 0.8 else
                 "unter Altersmedian – Schlaf, Stress, Alkohol, Ausdauertraining sind die größten Hebel")
            L.append(_rate("HRV (RMSSD)", v, f"{hrv:.0f} ms vs. Median ~{med} ms für {age} J."))
        else:
            L.append(_rate("HRV (RMSSD)", "nur Trend aussagekräftig", f"{hrv:.0f} ms"))

    asleep = _mean(r["asleep_ms"] for r in rows)
    if asleep is not None:
        h = asleep / 3_600_000
        lo, hi = (7, 8) if age and age >= 65 else (7, 9)
        short = sum(1 for r in rows if r["asleep_ms"] and r["asleep_ms"] < 7 * 3_600_000)
        n = sum(1 for r in rows if r["asleep_ms"])
        v = ("im Zielbereich ✅" if lo <= h <= hi else
             "zu kurz ⚠️" if h < lo else "über Empfehlung (ok, wenn erholt)")
        L.append(_rate("Schlafdauer", v, f"{h:.1f} h/Nacht, Ziel {lo}–{hi} h; {short}/{n} Nächte unter 7 h"))

    eff = _mean(r["sleep_eff"] for r in rows)
    if eff is not None:
        L.append(_rate("Schlafeffizienz", "normal ✅" if eff >= 85 else "unter 85 % ⚠️", f"{eff:.0f} %"))

    sws = _mean(100 * r["stages"].get("total_slow_wave_sleep_time_milli", 0) / r["asleep_ms"]
                for r in rows if r["asleep_ms"])
    rem = _mean(100 * r["stages"].get("total_rem_sleep_time_milli", 0) / r["asleep_ms"]
                for r in rows if r["asleep_ms"])
    if sws is not None:
        L.append(_rate("Schlafphasen",
                       "im typischen Bereich ✅" if 13 <= sws <= 25 and 18 <= rem <= 27 else "teilweise außerhalb typischer Werte",
                       f"Tiefschlaf {sws:.0f} % (typ. 13–23), REM {rem:.0f} % (typ. 20–25)"))

    resp = _mean(r["resp"] for r in rows)
    if resp is not None:
        L.append(_rate("Atemfrequenz (Schlaf)", "normal ✅" if 12 <= resp <= 20 else "außerhalb 12–20 ⚠️",
                       f"{resp:.1f} /min"))

    spo2 = _mean(r["spo2"] for r in rows)
    if spo2 is not None:
        lows = sum(1 for r in rows if r["spo2"] is not None and r["spo2"] < 90)
        v = "normal ✅" if spo2 >= 95 else "grenzwertig" if spo2 >= 90 else "niedrig ⚠️ – ärztlich abklären"
        L.append(_rate("SpO₂", v, f"{spo2:.0f} %" + (f", {lows} Nächte <90 %" if lows else "")))

    L += activity_lines(days.workouts, now)

    body = db.get("body") or {}
    if body.get("height_meter") and body.get("weight_kilogram"):
        bmi = body["weight_kilogram"] / body["height_meter"] ** 2
        v = ("Normalgewicht ✅" if 18.5 <= bmi < 25 else "Untergewicht" if bmi < 18.5 else
             "Übergewicht-Bereich (bei viel Muskulatur relativieren)" if bmi < 30 else "Adipositas-Bereich ⚠️")
        L.append(_rate("BMI", v, f"{bmi:.1f}"))
    if body.get("max_heart_rate") and age is not None:
        L.append(f"- **HFmax:** WHOOP nutzt {body['max_heart_rate']} bpm, Tanaka-Schätzung "
                 f"{208 - 0.7 * age:.0f} bpm")

    L += ["", "_Quellen/Normen:_"] + [f"- {k}: {v}" for k, v in REFERENCES.items()]
    return L


def activity_lines(workouts: list[dict], now: datetime) -> list[str]:
    """WHO activity minutes from WHOOP heart-rate zones of the last 7 days.

    WHOOP zones are %HFmax: 1 = 50–60, 2 = 60–70, 3 = 70–80, 4 = 80–90, 5 = 90–100.
    Zones 2–3 ≈ moderate, zones 4–5 ≈ vigorous intensity.
    """
    since = now - timedelta(days=7)
    mod = vig = 0.0
    strength = 0
    for w in workouts:
        start = datetime.fromisoformat(w["start"].replace("Z", "+00:00"))
        if start < since:
            continue
        name = (w.get("sport_name") or "").lower()
        if any(k in name for k in ("weight", "strength", "functional", "powerlifting", "kraft", "crossfit")):
            strength += 1
        z = (w.get("score") or {}).get("zone_durations") or {}
        mod += (z.get("zone_two_milli", 0) + z.get("zone_three_milli", 0)) / 60000
        vig += (z.get("zone_four_milli", 0) + z.get("zone_five_milli", 0)) / 60000
    equiv = mod + 2 * vig
    v = ("WHO-Empfehlung erfüllt ✅" if equiv >= 150 else "unter WHO-Minimum ⚠️")
    if equiv >= 300:
        v = "über dem WHO-Optimalbereich ✅✅"
    return [
        _rate("Aktivität (7 Tage, nur getrackte Workouts)", v,
              f"{mod:.0f} min moderat + {vig:.0f} min intensiv = {equiv:.0f} min moderat-äquivalent (Ziel 150–300)"),
        f"- **Kraft-Einheiten (7 Tage):** {strength} (WHO: ≥2)",
    ]
