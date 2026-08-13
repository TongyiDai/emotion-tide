from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "emotion-tide" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_module("emotion_tide_validator", SCRIPTS / "validate_analysis.py")
workday = load_module("emotion_tide_workday", SCRIPTS / "workday_gate.py")
renderer = load_module("emotion_tide_renderer", SCRIPTS / "render_dashboard.py")
reactions = load_module("emotion_tide_reactions", SCRIPTS / "extract_reaction_signals.py")
doctor = load_module("emotion_tide_doctor", SCRIPTS / "doctor.py")
probe = load_module("emotion_tide_probe", SCRIPTS / "lark_identity_probe.py")
backfill = load_module("emotion_tide_backfill", SCRIPTS / "backfill_plan.py")


class AnalysisContractTests(unittest.TestCase):
    def sample(self) -> dict:
        return json.loads((ROOT / "examples" / "analysis.sample.json").read_text(encoding="utf-8"))

    def test_sample_passes_and_daily_card_stays_lightweight(self) -> None:
        result = validator.validate(self.sample())
        svg = renderer.render(result)
        self.assertNotIn("六维状态轮廓", svg)
        self.assertIn("今日观察", svg)
        self.assertIn('clip-path="url(#summary-clip)"', svg)

    def test_dashboard_contract_requires_radar(self) -> None:
        contract = (ROOT / "skill" / "emotion-tide" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("六维状态轮廓", contract)
        self.assertIn("雷达图", contract)

    def test_weak_evidence_cannot_claim_precise_dimensions(self) -> None:
        payload = self.sample()
        payload.update({"message_count": 2, "effective_text_count": 2, "effective_char_count": 40})
        with self.assertRaisesRegex(ValueError, "weak evidence"):
            validator.validate(payload)

    def test_no_messages_have_exact_semantics(self) -> None:
        payload = self.sample()
        payload.update({
            "primary_emotion": "无本人消息",
            "secondary_emotions": [],
            "intensity": 0,
            "confidence": 0,
            "coverage": "no_user_messages",
            "message_count": 0,
            "effective_text_count": 0,
            "effective_char_count": 0,
            "dimensions": {key: None for key in validator.DIMENSIONS},
        })
        self.assertEqual(validator.validate(payload)["evidence_level"], "none")

    def test_extra_fields_are_rejected(self) -> None:
        payload = self.sample()
        payload["raw_messages"] = ["private text"]
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            validator.validate(payload)

    def test_reaction_counts_must_be_consistent(self) -> None:
        payload = self.sample()
        payload["effective_reaction_count"] = payload["reaction_count"] + 1
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            validator.validate(payload)

    def test_reactions_cannot_rescue_weak_text_evidence(self) -> None:
        payload = self.sample()
        payload.update({"message_count": 1, "effective_text_count": 1, "effective_char_count": 10, "reaction_count": 20, "effective_reaction_count": 15})
        with self.assertRaisesRegex(ValueError, "weak evidence"):
            validator.validate(payload)


class WorkdayGateTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "workday_calendar": {
                "year": 2026,
                "source_url": "https://www.gov.cn/",
                "workdays": ["2026-02-14"],
                "holidays": ["2026-02-16"],
            }
        }

    def test_makeup_saturday_is_workday(self) -> None:
        import datetime as dt

        self.assertEqual(workday.classify(dt.date(2026, 2, 14), self.config())["status"], "workday")

    def test_holiday_monday_is_non_workday(self) -> None:
        import datetime as dt

        self.assertEqual(workday.classify(dt.date(2026, 2, 16), self.config())["status"], "non_workday")

    def test_missing_year_fails_closed(self) -> None:
        import datetime as dt

        self.assertEqual(workday.classify(dt.date(2027, 1, 4), self.config())["status"], "unknown")

    def test_exit_code_is_three_for_non_workday(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(self.config()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "workday_gate.py"), "--config", str(config_path), "--date", "2026-02-16"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 3)

    def test_multi_year_calendar_resolves_prior_year(self) -> None:
        import datetime as dt

        config = {
            "workday_calendar": {
                "year": 2026,
                "workdays": [],
                "holidays": [],
                "years": [
                    {"year": 2025, "workdays": [], "holidays": ["2025-12-25"]},
                ],
            }
        }
        self.assertEqual(workday.classify(dt.date(2025, 12, 25), config)["status"], "non_workday")
        self.assertEqual(workday.classify(dt.date(2025, 12, 24), config)["status"], "workday")
        self.assertEqual(workday.classify(dt.date(2024, 1, 2), config)["status"], "unknown")


class BackfillPlanTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "timezone": "Asia/Shanghai",
            "workday_calendar": {
                "year": 2026,
                "source_url": "https://www.gov.cn/",
                "utc_offset": "+08:00",
                "workdays": [],
                "holidays": ["2026-02-16"],
                "years": [
                    {"year": 2025, "source_url": "https://www.gov.cn/", "workdays": [], "holidays": []},
                ],
            },
        }

    def test_plan_is_oldest_first_and_skips_non_workdays(self) -> None:
        import datetime as dt

        result = backfill.plan(
            self.config(),
            as_of=dt.date(2026, 2, 20),
            start=dt.date(2026, 2, 9),
            end=dt.date(2026, 2, 19),
            offset="+08:00",
            done=set(),
            limit=None,
        )
        dates = [item["date"] for item in result["pending"]]
        self.assertEqual(dates, sorted(dates))
        self.assertNotIn("2026-02-14", dates)  # Saturday
        self.assertNotIn("2026-02-15", dates)  # Sunday
        self.assertNotIn("2026-02-16", dates)  # official holiday
        self.assertTrue(result["calendar_complete"])
        first = result["pending"][0]
        self.assertEqual(first["start"], f"{first['date']}T00:00:00+08:00")

    def test_done_dates_are_idempotently_skipped(self) -> None:
        import datetime as dt

        result = backfill.plan(
            self.config(),
            as_of=dt.date(2026, 2, 20),
            start=dt.date(2026, 2, 9),
            end=dt.date(2026, 2, 13),
            offset="+08:00",
            done={"2026-02-09", "2026-02-10"},
            limit=None,
        )
        dates = [item["date"] for item in result["pending"]]
        self.assertNotIn("2026-02-09", dates)
        self.assertNotIn("2026-02-10", dates)
        self.assertEqual(result["counts"]["already_done"], 2)

    def test_limit_batches_and_reports_remaining(self) -> None:
        import datetime as dt

        result = backfill.plan(
            self.config(),
            as_of=dt.date(2026, 2, 20),
            start=dt.date(2026, 2, 9),
            end=dt.date(2026, 2, 13),
            offset="+08:00",
            done=set(),
            limit=2,
        )
        self.assertEqual(len(result["pending"]), 2)
        self.assertEqual(result["counts"]["pending"], 5)
        self.assertEqual(result["remaining_after_limit"], 3)

    def test_missing_year_marks_calendar_incomplete(self) -> None:
        import datetime as dt

        config = self.config()
        config["workday_calendar"]["years"] = []  # drop 2025
        result = backfill.plan(
            config,
            as_of=dt.date(2026, 1, 5),
            start=dt.date(2025, 12, 29),
            end=dt.date(2026, 1, 2),
            offset="+08:00",
            done=set(),
            limit=None,
        )
        self.assertFalse(result["calendar_complete"])
        self.assertIn("2025-12-29", result["unknown_dates"])

    def test_incomplete_calendar_exits_five(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.config()
            config["workday_calendar"]["years"] = []
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "backfill_plan.py"),
                    "--config", str(config_path),
                    "--as-of", "2026-01-05",
                    "--start", "2025-12-29",
                    "--end", "2026-01-02",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 5)

    def test_plan_emits_no_message_text_or_ids(self) -> None:
        import datetime as dt

        result = backfill.plan(
            self.config(),
            as_of=dt.date(2026, 2, 20),
            start=dt.date(2026, 2, 9),
            end=dt.date(2026, 2, 11),
            offset="+08:00",
            done=set(),
            limit=None,
        )
        blob = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("om_", blob)
        self.assertNotIn("ou_", blob)


class ReactionSignalTests(unittest.TestCase):
    def test_only_current_user_and_time_window_are_counted(self) -> None:
        payload = {
            "data": {
                "items": [{
                    "message_id": "om_message_a",
                    "msg_type": "text",
                    "reactions": {"details": [
                        {"reaction_id": "r1", "action_time": "1786464000000", "emoji_type": "THUMBSUP", "operator": {"operator_id": "test_user_self"}},
                        {"reaction_id": "r2", "action_time": "1786467600000", "emoji_type": "HEART", "operator": {"operator_id": "test_user_self"}},
                        {"reaction_id": "r3", "action_time": "1786467600000", "emoji_type": "ANGRY", "operator": {"operator_id": "test_user_other"}}
                    ]}
                }]
            }
        }
        result = reactions.aggregate(payload, "test_user_self", 1786460400000, 1786546800000, "complete")
        self.assertEqual(result["reaction_count"], 2)
        self.assertEqual(result["effective_reaction_count"], 1)
        self.assertEqual(result["reaction_signal"], "warmth")
        self.assertNotIn("om_message_a", json.dumps(result))
        self.assertNotIn("test_user_self", json.dumps(result))

    def test_acknowledgement_is_not_effective_emotion_evidence(self) -> None:
        payload = {"reaction_id": "r1", "action_time": "1786464000000", "emoji_type": "LGTM", "operator": {"operator_id": "me"}}
        result = reactions.aggregate(payload, "me", 1786460400000, 1786546800000, "complete")
        self.assertEqual(result["reaction_signal"], "acknowledgement")
        self.assertEqual(result["effective_reaction_count"], 0)


class ProvisioningTests(unittest.TestCase):
    def example(self) -> dict:
        return json.loads((ROOT / "skill" / "emotion-tide" / "config.example.json").read_text(encoding="utf-8"))

    def test_public_example_contains_no_reusable_identity_or_base(self) -> None:
        config = self.example()
        self.assertEqual(config["provisioning_state"], "unprovisioned")
        self.assertIsNone(config["owner_user_id"])
        self.assertIsNone(config["recipient_user_id"])
        self.assertTrue(all(value is None for value in config["base"].values()))

    def test_unprovisioned_config_is_only_allowed_in_bootstrap_mode(self) -> None:
        config = self.example()
        config.update({"installation_id": "install_a", "lark_profile": "personal", "text_processing_consent": True})
        self.assertTrue(all(doctor.config_checks(config, allow_unprovisioned=True).values()))
        self.assertFalse(all(doctor.config_checks(config, allow_unprovisioned=False).values()))

    def test_legacy_config_with_base_ids_never_infers_ready(self) -> None:
        config = self.example()
        config.pop("provisioning_state")
        config.update({
            "installation_id": None,
            "lark_profile": "personal",
            "text_processing_consent": True,
            "owner_user_id": None,
            "recipient_user_id": "user_a",
            "base": {"url": "https://example.invalid/base/a", "base_token": "base_a", "table_id": "table_a", "dashboard_id": "dashboard_a"},
        })
        checks = doctor.config_checks(config, allow_unprovisioned=True)
        self.assertFalse(checks["config_structure"])
        self.assertFalse(checks["installation_id_configured"])
        self.assertFalse(checks["provisioning_state_explicit"])
        self.assertFalse(checks["provisioning_state_valid"])
        self.assertFalse(checks["owner_binding_configured"])

    def test_unprovisioned_binding_cannot_be_one_sided(self) -> None:
        config = self.example()
        config.update({
            "installation_id": "install_a",
            "lark_profile": "personal",
            "text_processing_consent": True,
            "recipient_user_id": "user_a",
        })
        self.assertFalse(doctor.config_checks(config, allow_unprovisioned=True)["owner_binding_configured"])

    def test_ready_config_requires_same_owner_and_recipient(self) -> None:
        config = self.example()
        config.update({
            "provisioning_state": "ready",
            "lark_profile": "personal",
            "text_processing_consent": True,
            "owner_user_id": "user_a",
            "recipient_user_id": "user_b",
            "base": {"url": "https://example.invalid/base/a", "base_token": "base_a", "table_id": "table_a", "dashboard_id": "dashboard_a"},
        })
        self.assertFalse(doctor.config_checks(config, allow_unprovisioned=False)["owner_binding_configured"])

    def test_placeholders_are_never_real_values(self) -> None:
        self.assertFalse(doctor.real_value("YOUR_BASE_TOKEN"))
        self.assertFalse(doctor.real_value(None))
        self.assertTrue(doctor.real_value("base_created_for_current_user"))

    def test_ready_base_probe_uses_configured_profile_and_user_identity(self) -> None:
        config = self.example()
        config.update({"lark_profile": "personal", "base": {"base_token": "base_a"}})
        completed = SimpleNamespace(returncode=0, stdout='{"ok":true,"identity":"user"}')
        with mock.patch.object(doctor.subprocess, "run", return_value=completed) as run:
            self.assertTrue(doctor.ready_base_is_accessible(config, {}))
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("--profile") + 1], "personal")
        self.assertEqual(argv[argv.index("--as") + 1], "user")

    def test_ready_base_probe_fails_closed_on_forbidden(self) -> None:
        config = self.example()
        config.update({"lark_profile": "personal", "base": {"base_token": "base_a"}})
        completed = SimpleNamespace(returncode=1, stdout="")
        with mock.patch.object(doctor.subprocess, "run", return_value=completed):
            self.assertFalse(doctor.ready_base_is_accessible(config, {}))


class IdentityProbeTests(unittest.TestCase):
    def completed(self, *, returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def test_supported_auth_failure_never_falls_through_to_contact(self) -> None:
        with mock.patch.object(probe.shutil, "which", return_value="/usr/bin/lark-cli"), mock.patch.object(
            probe.subprocess,
            "run",
            side_effect=[
                self.completed(returncode=1, stdout='{"identity":"bot","verified":false}'),
            ],
        ) as run:
            result = probe.probe_lark_identity()
        self.assertFalse(result["ok"])
        self.assertEqual(result["method"], "auth_status")
        self.assertTrue(result["auth_supported"])
        self.assertEqual(run.call_count, 1)

    def test_contact_probe_resolves_subject_when_auth_command_is_missing(self) -> None:
        with mock.patch.object(probe.shutil, "which", return_value="/usr/bin/lark-cli"), mock.patch.object(
            probe.subprocess,
            "run",
            side_effect=[
                self.completed(returncode=1, stderr="unknown command 'auth'"),
                self.completed(returncode=0, stdout='{"ok":true,"identity":"user","data":{"user":{"open_id":"ou_123"}}}'),
            ],
        ):
            result = probe.probe_lark_identity(require_subject=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "contact_self")
        self.assertEqual(result["identity_assurance"], "resolved")
        self.assertEqual(result["subject_id"], "ou_123")

    def test_task_canary_cannot_satisfy_subject_requirement(self) -> None:
        with mock.patch.object(probe.shutil, "which", return_value="/usr/bin/lark-cli"), mock.patch.object(
            probe.subprocess,
            "run",
            side_effect=[
                self.completed(returncode=1, stderr="unknown command 'auth'"),
                self.completed(returncode=1, stdout='{"ok":false}'),
                self.completed(returncode=0, stdout='{"ok":true,"identity":"user","data":{"items":[]}}'),
            ],
        ):
            result = probe.probe_lark_identity(require_subject=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["method"], "task_canary")
        self.assertEqual(result["identity_assurance"], "user_context")


if __name__ == "__main__":
    unittest.main()
