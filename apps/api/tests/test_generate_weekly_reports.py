"""Tests para el cron de borradores de reportes semanales."""

from __future__ import annotations

from datetime import date

from apps.api.scripts.generate_weekly_reports import previous_week, recipient_from_extra


class TestPreviousWeek:
    def test_monday_generates_previous_monday_to_sunday(self) -> None:
        start, end = previous_week(date(2026, 6, 1))

        assert start == date(2026, 5, 25)
        assert end == date(2026, 5, 31)

    def test_midweek_still_targets_previous_full_week(self) -> None:
        start, end = previous_week(date(2026, 6, 4))

        assert start == date(2026, 5, 25)
        assert end == date(2026, 5, 31)


class TestRecipientFromExtra:
    def test_prefers_weekly_report_recipient_email(self) -> None:
        assert (
            recipient_from_extra(
                {
                    "weekly_report_recipient_email": " ops@client.test ",
                    "notif_email": "fallback@client.test",
                }
            )
            == "ops@client.test"
        )

    def test_accepts_json_string_extra(self) -> None:
        assert (
            recipient_from_extra('{"weekly_report_email": "weekly@client.test"}')
            == "weekly@client.test"
        )

    def test_returns_none_when_missing(self) -> None:
        assert recipient_from_extra({"currency": "EUR"}) is None
