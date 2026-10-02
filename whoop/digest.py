"""Turn the raw WHOOP history into a compact, numbers-first digest.

The digest is deterministic (all statistics are computed here); Claude reads it
and writes the coaching text on top. See CLAUDE.md for the coaching rules.
"""

import statistics
from datetime import datetime, timedelta, timezone

from . import reference

H = 3_600_000  # ms per hour


# ---------- helpers ----------

def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _local(s: str | None, offset: str | None) -> datetime | None:
    dt = _dt(s)
    if dt is None:
        return None
    if offset:
        sign = -1 if offset.startswith("-") else 1
        hh, mm = offset.lstrip("+-").split(":")
        dt = dt.astimezone(timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    return dt


def _scored(rec: dict) -> dict | None:
    return rec.get("score") if rec.get("score_state") == "SCORED" else None


def _fmt(v, nd=0, unit=""):
    if v is None:
        return "–"
    return f"{v:.{nd}f}{unit}"


def _hm(ms: float | None) -> str:
    if ms is None:
        return "–"
    m = round(ms / 60000)
    return f"{m // 60}:{m % 60:02d} h"


def _wd(d) -> str:
    return ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"][d.weekday()]


def _clock(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "–"


class Stat:
    def __init__(self, values):
        self.values = [v for v in values if v is not None]
        self.n = len(self.values)
        self.mean = statistics.fmean(self.values) if self.values else None
        self.sd = statistics.stdev(self.values) if self.n >= 3 else None

    def z(self, v):
        if v is None or self.mean is None or not self.sd:
            return None
        return (v - self.mean) / self.sd


def _dev(v, stat: Stat, nd=0, unit="", higher_is_better=True) -> str:
    """'62 ms (Ø 30T 55 ±6, +1.2σ ↑ gut)'"""
    if v is None:
        return "–"
    s = _fmt(v, nd, unit)
    if stat.mean is None:
        return s
    s += f" (Ø30T {_fmt(stat.mean, nd)}"
    if stat.sd:
        s += f" ±{_fmt(stat.sd, nd)}"
    z = stat.z(v)
    if z is not None:
        good = (z > 0) == higher_is_better
        tag = ""
        if abs(z) >= 1:
            tag = " ✅" if good else " ⚠️"
        s += f", {z:+.1f}σ{tag}"
    return s + ")"


# ---------- data model ----------

class Days:
    """One row per physiological cycle (≈ one day, wake-to-wake)."""

    def __init__(self, db: dict):
        cycles = sorted(db.get("cycles", {}).values(), key=lambda c: c["start"])
        recs = db.get("recoveries", {})
        sleeps = {s["id"]: s for s in db.get("sleeps", {}).values()}
        self.workouts = sorted(db.get("workouts", {}).values(), key=lambda w: w["start"])
        self.naps = [s for s in sleeps.values() if s.get("nap")]
        self.rows = []
        for c in cycles:
            r = recs.get(str(c["id"])) or {}
            rs = _scored(r) or {}
            sl = sleeps.get(r.get("sleep_id")) or {}
            ss = _scored(sl) or {}
            stages = ss.get("stage_summary") or {}
            need = ss.get("sleep_needed") or {}
            asleep = None
            if stages:
                asleep = (stages.get("total_light_sleep_time_milli", 0)
                          + stages.get("total_slow_wave_sleep_time_milli", 0)
                          + stages.get("total_rem_sleep_time_milli", 0))
            need_total = sum(need.get(k, 0) for k in (
                "baseline_milli", "need_from_sleep_debt_milli",
                "need_from_recent_strain_milli", "need_from_recent_nap_milli")) if need else None
            cs = _scored(c) or {}
            start = _local(c["start"], c.get("timezone_offset"))
            self.rows.append({
                "cycle": c,
                "date": start.date() if start else None,
                "recovery": rs.get("recovery_score"),
                "recovery_state": r.get("score_state"),
                "calibrating": rs.get("user_calibrating"),
                "hrv": rs.get("hrv_rmssd_milli"),
                "rhr": rs.get("resting_heart_rate"),
                "spo2": rs.get("spo2_percentage"),
                "skin_temp": rs.get("skin_temp_celsius"),
                "strain": cs.get("strain"),
                "strain_final": c.get("end") is not None,
                "kj": cs.get("kilojoule"),
                "sleep": sl,
                "asleep_ms": asleep,
                "need_ms": need_total,
                "need": need,
                "stages": stages,
                "sleep_perf": ss.get("sleep_performance_percentage"),
                "sleep_eff": ss.get("sleep_efficiency_percentage"),
                "sleep_cons": ss.get("sleep_consistency_percentage"),
                "resp": ss.get("respiratory_rate"),
                "bed": _local(sl.get("start"), sl.get("timezone_offset")),
                "wake": _local(sl.get("end"), sl.get("timezone_offset")),
            })

    def baseline(self, field: str, upto: int, days: int = 30) -> Stat:
        """Stats over the `days` rows before index `upto` (exclusive)."""
        window = self.rows[max(0, upto - days):upto]
        if field == "strain":
            window = [r for r in window if r["strain_final"]]
        return Stat(r[field] for r in window)

    def workouts_between(self, start: datetime, end: datetime | None) -> list[dict]:
        out = []
        for w in self.workouts:
            ws = _dt(w["start"])
            if ws >= start and (end is None or ws < end):
                out.append(w)
        return out


# ---------- sections ----------

def _recovery_section(d: Days, i: int) -> list[str]:
    r = d.rows[i]
    L = ["## Recovery heute"]
    if r["recovery"] is None:
        L.append(f"- Noch nicht berechnet (Status: {r['recovery_state'] or 'keine Daten'}).")
        return L
    zone = "GRÜN" if r["recovery"] >= 67 else "GELB" if r["recovery"] >= 34 else "ROT"
    L.append(f"- Recovery: **{zone}** {_dev(r['recovery'], d.baseline('recovery', i), 0, ' %')}")
    if r["calibrating"]:
        L.append("- Hinweis: WHOOP kalibriert noch (erste Wochen) – Werte mit Vorsicht.")
    L.append(f"- HRV: {_dev(r['hrv'], d.baseline('hrv', i), 0, ' ms')}")
    L.append(f"- Ruhepuls: {_dev(r['rhr'], d.baseline('rhr', i), 0, ' bpm', higher_is_better=False)}")
    L.append(f"- Atemfrequenz: {_dev(r['resp'], d.baseline('resp', i), 1, '/min', higher_is_better=False)}")
    if r["skin_temp"] is not None:
        st = d.baseline("skin_temp", i)
        delta = f" (Δ {r['skin_temp'] - st.mean:+.1f} °C ggü. Ø)" if st.mean is not None else ""
        L.append(f"- Hauttemperatur: {r['skin_temp']:.1f} °C{delta}")
    if r["spo2"] is not None:
        L.append(f"- SpO₂: {r['spo2']:.0f} %")
    return L


def _sleep_section(d: Days, i: int, title="## Letzte Nacht") -> list[str]:
    r = d.rows[i]
    L = [title]
    if not r["stages"]:
        L.append("- Keine bewertete Hauptschlafphase.")
        return L
    st = r["stages"]
    L.append(f"- Zeit: {_clock(r['bed'])} → {_clock(r['wake'])}, "
             f"im Bett {_hm(st.get('total_in_bed_time_milli'))}, geschlafen **{_hm(r['asleep_ms'])}** "
             f"von benötigt {_hm(r['need_ms'])}")
    if r["asleep_ms"] and r["need_ms"]:
        L.append(f"- Bedarf gedeckt: {100 * r['asleep_ms'] / r['need_ms']:.0f} % "
                 f"(Bedarf = Basis {_hm(r['need'].get('baseline_milli'))} + Schlafschuld "
                 f"{_hm(r['need'].get('need_from_sleep_debt_milli'))} + Belastung "
                 f"{_hm(r['need'].get('need_from_recent_strain_milli'))})")
    L.append(f"- Schlafleistung: {_dev(r['sleep_perf'], d.baseline('sleep_perf', i), 0, ' %')}")
    L.append(f"- Effizienz: {_fmt(r['sleep_eff'], 0, ' %')}, Konsistenz: {_fmt(r['sleep_cons'], 0, ' %')}")
    a = r["asleep_ms"] or 1
    L.append(f"- Phasen: Tief {_hm(st.get('total_slow_wave_sleep_time_milli'))} "
             f"({100 * st.get('total_slow_wave_sleep_time_milli', 0) / a:.0f} %), "
             f"REM {_hm(st.get('total_rem_sleep_time_milli'))} "
             f"({100 * st.get('total_rem_sleep_time_milli', 0) / a:.0f} %), "
             f"Leicht {_hm(st.get('total_light_sleep_time_milli'))}, "
             f"wach {_hm(st.get('total_awake_time_milli'))}, "
             f"Störungen {st.get('disturbance_count', '–')}, Zyklen {st.get('sleep_cycle_count', '–')}")
    return L


def _workout_lines(ws: list[dict]) -> list[str]:
    L = []
    for w in ws:
        s = _scored(w) or {}
        start = _local(w["start"], w.get("timezone_offset"))
        dur = (_dt(w["end"]) - _dt(w["start"])).total_seconds() * 1000 if w.get("end") else None
        line = (f"- {_clock(start)} **{w.get('sport_name', 'Workout')}** {_hm(dur)}: "
                f"Strain {_fmt(s.get('strain'), 1)}, Ø HF {_fmt(s.get('average_heart_rate'))}, "
                f"max {_fmt(s.get('max_heart_rate'))}, {_fmt((s.get('kilojoule') or 0) / 4.184, 0, ' kcal')}")
        if s.get("distance_meter"):
            line += f", {s['distance_meter'] / 1000:.1f} km"
        z = s.get("zone_durations") or {}
        if z:
            tot = sum(z.values()) or 1
            names = ["zone_zero_milli", "zone_one_milli", "zone_two_milli",
                     "zone_three_milli", "zone_four_milli", "zone_five_milli"]
            line += " | Zonen 0–5: " + "/".join(f"{100 * z.get(n, 0) / tot:.0f}" for n in names) + " %"
        if w.get("score_state") != "SCORED":
            line += f" (Status {w.get('score_state')})"
        L.append(line)
    return L or ["- keine Workouts"]


def _strain_section(d: Days, i: int, title: str) -> list[str]:
    r = d.rows[i]
    c = r["cycle"]
    L = [title]
    L.append(f"- Tages-Strain: **{_fmt(r['strain'], 1)}**{'' if r['strain_final'] else ' (läuft noch)'}"
             f" – Ø30T {_fmt(d.baseline('strain', i).mean, 1)}, "
             f"Energie {_fmt((r['kj'] or 0) / 4.184, 0, ' kcal')}")
    L.extend(_workout_lines(d.workouts_between(_dt(c["start"]), _dt(c.get("end")))))
    return L


def _target_strain(recovery) -> str:
    if recovery is None:
        return "–"
    if recovery >= 67:
        return "14–18 (grün: harte Einheit möglich)"
    if recovery >= 34:
        return "10–14 (gelb: moderat, Technik/Grundlage)"
    return "0–10 (rot: aktive Erholung, Mobility, Spaziergang)"


def _trend_section(d: Days, i: int) -> list[str]:
    last7 = d.rows[max(0, i - 6):i + 1]
    L = ["## 7-Tage-Trend (älteste → heute)"]
    L.append("| Tag | Rec % | HRV | RHR | Schlaf | Bedarf | Strain |")
    L.append("|---|---|---|---|---|---|---|")
    for r in last7:
        L.append(f"| {_wd(r['date'])[:2]} {r['date']:%d.%m} | {_fmt(r['recovery'])} | {_fmt(r['hrv'])} | {_fmt(r['rhr'])} "
                 f"| {_hm(r['asleep_ms'])} | {_hm(r['need_ms'])} | {_fmt(r['strain'], 1)} |")

    def avg(rows, f):
        vals = [x[f] for x in rows if x[f] is not None and (f != "strain" or x["strain_final"])]
        return statistics.fmean(vals) if vals else None

    prev = d.rows[max(0, i - 30):i + 1]
    acute, chronic = avg(d.rows[max(0, i - 7):i], "strain"), avg(d.rows[max(0, i - 28):i], "strain")
    L.append("")
    for f, name, nd in (("recovery", "Recovery", 0), ("hrv", "HRV", 0), ("rhr", "Ruhepuls", 0)):
        L.append(f"- {name}: Ø7T {_fmt(avg(last7, f), nd)} vs Ø30T {_fmt(avg(prev, f), nd)}")
    sleep7, need7 = avg(last7, "asleep_ms"), avg(last7, "need_ms")
    L.append(f"- Schlaf: Ø7T {_hm(sleep7)} vs Bedarf Ø7T {_hm(need7)}")
    if acute and chronic:
        L.append(f"- Belastung: Ø-Strain 7T {acute:.1f} vs 28T {chronic:.1f} → Verhältnis {acute / chronic:.2f} "
                 f"(>1.3 = deutlich mehr als gewohnt, <0.8 = Entlastung)")
    beds = [r["bed"] for r in last7 if r["bed"]]
    wakes = [r["wake"] for r in last7 if r["wake"]]
    if len(beds) >= 3:
        def spread(dts):
            mins = [((t.hour * 60 + t.minute + 720) % 1440) for t in dts]  # noon-anchored
            return max(mins) - min(mins)
        L.append(f"- Einschlafzeiten schwanken um {spread(beds)} min, Aufwachzeiten um {spread(wakes)} min (7T)")
    return L


def _bedtime_hint(d: Days, i: int) -> list[str]:
    wakes = [r["wake"] for r in d.rows[max(0, i - 13):i + 1] if r["wake"]]
    need = d.rows[i]["need_ms"] or d.baseline("need_ms", i).mean
    if not wakes or not need:
        return []
    mins = sorted(((w.hour * 60 + w.minute) for w in wakes))
    wake_min = mins[len(mins) // 2]
    eff = (d.baseline("sleep_eff", i + 1).mean or 90) / 100
    bed_min = int(wake_min - need / 60000 / eff) % 1440
    return [f"- Typische Aufwachzeit (Median 14T): {wake_min // 60:02d}:{wake_min % 60:02d} → "
            f"für ~{_hm(need)} Schlaf bei {eff * 100:.0f} % Effizienz ins Bett bis ca. "
            f"**{bed_min // 60:02d}:{bed_min % 60:02d}**"]


# ---------- public ----------

def build(db: dict, mode: str = "morning", now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    d = Days(db)
    if not d.rows:
        return "# WHOOP Digest\n\nNoch keine Daten vorhanden – Synchronisierung prüfen."
    i = len(d.rows) - 1
    synced = _dt(db.get("synced_at"))
    age_h = (now - synced).total_seconds() / 3600 if synced else None
    today = d.rows[i]

    title = {"morning": "Morgen", "evening": "Abend", "weekly": "Wochen-Check"}.get(mode, mode)
    L = [f"# WHOOP Digest – {title}, {_wd(today['date'])} {today['date']:%d.%m.%Y}",
         f"_Daten synchronisiert vor {_fmt(age_h, 1)} h; {len(d.rows)} Tage Historie._"]
    if age_h is not None and age_h > 3:
        L.append("⚠️ **Daten sind älter als 3 h – Sync-Workflow prüfen.**")
    if db.get("profile"):
        p, b = db["profile"], db.get("body") or {}
        L.append(f"_Person: {p.get('first_name', '')}, max HF {_fmt(b.get('max_heart_rate'))}, "
                 f"{_fmt(b.get('weight_kilogram'), 1, ' kg')}_")
    L.append("")

    if mode == "morning":
        L += _recovery_section(d, i) + [""]
        L += _sleep_section(d, i) + [""]
        if i >= 1:
            L += _strain_section(d, i - 1, "## Gestern: Belastung") + [""]
        L += ["## Heute", f"- Strain-Zielkorridor (Heuristik): {_target_strain(today['recovery'])}"]
        L += [""] + _trend_section(d, i)
        L += [""] + reference.section(d, i, db, now)
    elif mode == "evening":
        L += _strain_section(d, i, "## Heute: Belastung bisher") + [""]
        L += [f"- Recovery heute morgen: {_fmt(today['recovery'], 0, ' %')} → Zielkorridor war "
              f"{_target_strain(today['recovery'])}"]
        L += reference.activity_lines(d.workouts, now)
        L += [""] + _sleep_section(d, i, "## Schlaf letzte Nacht (Kurz)")[:3]
        L += ["", "## Heute Abend"] + _bedtime_hint(d, i)
        L += [""] + _trend_section(d, i)
    elif mode == "weekly":
        L += _weeks_section(d, i) + [""]
        L += reference.section(d, i, db, now) + [""]
        L += _trend_section(d, i)
    else:
        raise ValueError(f"unknown mode {mode!r}")
    return "\n".join(L)


def _weeks_section(d: Days, i: int, weeks: int = 4) -> list[str]:
    L = ["## Wochenvergleich (Ø je Woche, neueste zuerst)",
         "| Woche | Rec % | HRV | RHR | Schlaf | Schlafleistung | Strain | Workouts |",
         "|---|---|---|---|---|---|---|---|"]
    for w in range(weeks):
        rows = d.rows[max(0, i - 7 * (w + 1) + 1):i - 7 * w + 1]
        if not rows:
            break

        def avg(f):
            vals = [r[f] for r in rows if r[f] is not None]
            return statistics.fmean(vals) if vals else None

        n_w = len(d.workouts_between(_dt(rows[0]["cycle"]["start"]),
                                     _dt(rows[-1]["cycle"].get("end"))))
        L.append(f"| {rows[0]['date']:%d.%m}–{rows[-1]['date']:%d.%m} | {_fmt(avg('recovery'))} | "
                 f"{_fmt(avg('hrv'))} | {_fmt(avg('rhr'))} | {_hm(avg('asleep_ms'))} | "
                 f"{_fmt(avg('sleep_perf'), 0, ' %')} | {_fmt(avg('strain'), 1)} | {n_w} |")
    return L
