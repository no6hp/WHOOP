import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from whoop import api, digest, store, sync

NOW = datetime(2026, 10, 2, 7, 30, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fake_db(days=40, seed=1):
    rnd = random.Random(seed)
    db = {"cycles": {}, "recoveries": {}, "sleeps": {}, "workouts": {},
          "profile": {"first_name": "Test"},
          "body": {"height_meter": 1.8, "weight_kilogram": 78.0, "max_heart_rate": 190},
          "synced_at": (NOW - timedelta(minutes=20)).isoformat()}
    for n in range(days):
        wake = NOW - timedelta(days=days - 1 - n, hours=2)
        bed = wake - timedelta(hours=8)
        cid, sid = 1000 + n, f"s-{n}"
        last = n == days - 1
        db["cycles"][str(cid)] = {
            "id": cid, "start": iso(wake), "end": None if last else iso(wake + timedelta(days=1)),
            "timezone_offset": "+02:00", "score_state": "SCORED",
            "score": {"strain": rnd.uniform(6, 17), "kilojoule": 10000, "average_heart_rate": 70, "max_heart_rate": 170}}
        db["recoveries"][str(cid)] = {
            "cycle_id": cid, "sleep_id": sid, "score_state": "SCORED",
            "score": {"user_calibrating": False, "recovery_score": rnd.uniform(30, 95),
                      "resting_heart_rate": rnd.uniform(50, 58), "hrv_rmssd_milli": rnd.uniform(45, 80),
                      "spo2_percentage": 96.5, "skin_temp_celsius": 33.4}}
        light, sws, rem = 3.6e6 * 3.6, 3.6e6 * 1.5, 3.6e6 * 1.7
        db["sleeps"][sid] = {
            "id": sid, "cycle_id": cid, "nap": False, "start": iso(bed), "end": iso(wake),
            "timezone_offset": "+02:00", "score_state": "SCORED",
            "score": {"stage_summary": {"total_in_bed_time_milli": 8 * 3.6e6, "total_awake_time_milli": 0.5 * 3.6e6,
                                        "total_no_data_time_milli": 0, "total_light_sleep_time_milli": light,
                                        "total_slow_wave_sleep_time_milli": sws, "total_rem_sleep_time_milli": rem,
                                        "sleep_cycle_count": 4, "disturbance_count": 7},
                      "sleep_needed": {"baseline_milli": 7.5 * 3.6e6, "need_from_sleep_debt_milli": 0.3 * 3.6e6,
                                       "need_from_recent_strain_milli": 0.2 * 3.6e6, "need_from_recent_nap_milli": 0},
                      "respiratory_rate": 14.8, "sleep_performance_percentage": rnd.uniform(70, 98),
                      "sleep_consistency_percentage": 80, "sleep_efficiency_percentage": 93}}
        if n % 2 == 0:
            ws = wake + timedelta(hours=9)
            db["workouts"][f"w-{n}"] = {
                "id": f"w-{n}", "start": iso(ws), "end": iso(ws + timedelta(minutes=50)),
                "timezone_offset": "+02:00", "sport_name": "running", "score_state": "SCORED",
                "score": {"strain": 11.2, "average_heart_rate": 148, "max_heart_rate": 176, "kilojoule": 2500,
                          "distance_meter": 9000,
                          "zone_durations": {"zone_zero_milli": 0, "zone_one_milli": 300000,
                                             "zone_two_milli": 900000, "zone_three_milli": 1200000,
                                             "zone_four_milli": 480000, "zone_five_milli": 120000}}}
    return db


class DigestTest(unittest.TestCase):
    def test_all_modes_render(self):
        db = fake_db()
        for mode in ("morning", "evening", "weekly"):
            with mock.patch.dict(os.environ, {"WHOOP_BIRTH_YEAR": "1990"}):
                out = digest.build(db, mode, NOW)
            self.assertIn("WHOOP Digest", out)
            self.assertNotIn("älter als 3 h", out)
            if mode != "evening":
                self.assertIn("Einordnung nach Fachstandards", out)
                self.assertIn("vs. Median", out)
        self.assertIn("Recovery:", digest.build(db, "morning", NOW))
        self.assertIn("ins Bett bis ca.", digest.build(db, "evening", NOW))
        self.assertIn("Wochenvergleich", digest.build(db, "weekly", NOW))

    def test_data_timestamp_in_berlin_time(self):
        db = fake_db(days=5)
        db["checked_at"] = (NOW - timedelta(minutes=25)).isoformat()   # 07:05 UTC
        out = digest.build(db, "morning", NOW)
        # Newest record ends 07:30 UTC -> 09:30 Berlin (CEST); last check 09:05.
        self.assertIn("Datenstand: heute 09:30 Uhr", out)
        self.assertIn("zuletzt abgerufen heute 09:05 Uhr", out)

    def test_no_stale_warning_when_checked_recently_without_new_data(self):
        db = fake_db(days=5)
        db["synced_at"] = (NOW - timedelta(hours=8)).isoformat()
        db["checked_at"] = (NOW - timedelta(minutes=30)).isoformat()
        self.assertNotIn("älter als 3 h", digest.build(db, "morning", NOW))

    def test_activity_minutes(self):
        out = digest.build(fake_db(), "evening", NOW)
        # 4 runs in the last 7 days à 35 min moderate + 10 min vigorous -> 4 * 55 = 220
        self.assertIn("220 min moderat-äquivalent", out)

    def test_pending_and_empty(self):
        db = fake_db(days=3)
        last = max(db["recoveries"], key=int)
        db["recoveries"][last] = {"cycle_id": int(last), "score_state": "PENDING_SCORE"}
        self.assertIn("Noch nicht berechnet", digest.build(db, "morning", NOW))
        self.assertIn("Noch keine Daten", digest.build({}, "morning", NOW))

    def test_stale_warning(self):
        db = fake_db(days=5)
        db["synced_at"] = (NOW - timedelta(hours=5)).isoformat()
        self.assertIn("älter als 3 h", digest.build(db, "morning", NOW))


class StoreAndSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(store, "DATA_FILE", d / "whoop.json.enc"),
            mock.patch.object(store, "TOKEN_FILE", d / "token.json.enc"),
            mock.patch.dict(os.environ, {"WHOOP_DATA_KEY": "k" * 32, "WHOOP_CLIENT_ID": "id",
                                         "WHOOP_CLIENT_SECRET": "secret"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_roundtrip_is_encrypted(self):
        store.save(store.DATA_FILE, {"hrv": 55})
        self.assertNotIn(b"hrv", store.DATA_FILE.read_bytes())
        self.assertEqual(store.load(store.DATA_FILE), {"hrv": 55})
        with mock.patch.dict(os.environ, {"WHOOP_DATA_KEY": "wrong"}):
            with self.assertRaises(SystemExit):
                store.load(store.DATA_FILE)

    def test_sync_refreshes_and_merges(self):
        store.save(store.TOKEN_FILE, {"access_token": "old", "refresh_token": "r1", "expires_at": 0})
        src = fake_db(days=3)

        class FakeClient:
            def __init__(self, token):
                assert token == "new"

            def collection(self, path, start=None, end=None):
                kind = {v: k for k, v in api.COLLECTIONS.items()}[path]
                return list(src[kind].values())

            def profile(self):
                return src["profile"]

            def body(self):
                return src["body"]

        with mock.patch.object(api, "refresh", return_value={"access_token": "new", "refresh_token": "r2",
                                                             "expires_at": 9e12}), \
                mock.patch.object(api, "Client", FakeClient):
            res = sync.sync(NOW)
            self.assertTrue(res["changed"])
            self.assertFalse(sync.sync(NOW)["changed"])

        self.assertEqual(store.load(store.TOKEN_FILE)["refresh_token"], "r2")
        db = store.load(store.DATA_FILE)
        self.assertEqual(len(db["recoveries"]), 3)
        self.assertIn("Recovery", digest.build(db, "morning", NOW))


class CredentialsTest(unittest.TestCase):
    def test_strips_pasted_whitespace_and_quotes(self):
        with mock.patch.dict(os.environ, {"WHOOP_CLIENT_ID": ' "abc-123"\n', "WHOOP_CLIENT_SECRET": "s3 \n"}):
            self.assertEqual(sync.credentials(), ("abc-123", "s3"))


class ApiTest(unittest.TestCase):
    def test_auth_url(self):
        url = api.authorization_url("cid", "https://github.com/x/y")
        self.assertIn("client_id=cid", url)
        self.assertIn("offline", url)
        self.assertRegex(url, r"state=[0-9a-f]{16}")

    def test_requests_send_custom_user_agent(self):
        import io
        seen = []

        def fake_urlopen(req, timeout=None):
            seen.append(req.get_header("User-agent"))
            return io.BytesIO(b'{"access_token": "a", "refresh_token": "r", "records": []}')

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            api.exchange_code("i", "s", "https://x", "c")
            api.Client("a").collection("/v2/cycle")
        self.assertEqual(seen, [api.USER_AGENT, api.USER_AGENT])

    def test_refresh_keeps_old_token_if_not_rotated(self):
        with mock.patch.object(api, "_post_form", return_value={"access_token": "a", "expires_in": 3600}):
            self.assertEqual(api.refresh("i", "s", {"refresh_token": "r"})["refresh_token"], "r")


if __name__ == "__main__":
    unittest.main()
