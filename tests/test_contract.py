from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class ReactionSignalTests(unittest.TestCase):
    def test_only_current_user_and_time_window_are_counted(self) -> None:
        payload = {
            "data": {
                "items": [{
                    "message_id": "om_message_a",
                    "msg_type": "text",
                    "reactions": {"details": [
                        {"reaction_id": "r1", "action_time": "1786464000000", "emoji_type": "THUMBSUP", "operator": {"operator_id": "ou_self"}},
                        {"reaction_id": "r2", "action_time": "1786467600000", "emoji_type": "HEART", "operator": {"operator_id": "ou_self"}},
                        {"reaction_id": "r3", "action_time": "1786467600000", "emoji_type": "ANGRY", "operator": {"operator_id": "ou_other"}}
                    ]}
                }]
            }
        }
        result = reactions.aggregate(payload, "ou_self", 1786460400000, 1786546800000, "complete")
        self.assertEqual(result["reaction_count"], 2)
        self.assertEqual(result["effective_reaction_count"], 1)
        self.assertEqual(result["reaction_signal"], "warmth")
        self.assertNotIn("om_message_a", json.dumps(result))
        self.assertNotIn("ou_self", json.dumps(result))

    def test_acknowledgement_is_not_effective_emotion_evidence(self) -> None:
        payload = {"reaction_id": "r1", "action_time": "1786464000000", "emoji_type": "LGTM", "operator": {"operator_id": "me"}}
        result = reactions.aggregate(payload, "me", 1786460400000, 1786546800000, "complete")
        self.assertEqual(result["reaction_signal"], "acknowledgement")
        self.assertEqual(result["effective_reaction_count"], 0)


if __name__ == "__main__":
    unittest.main()
