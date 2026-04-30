"""APScheduler — daily scrape, weekly report, daily match email."""
import asyncio
import logging
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_async(coro):
    """Run an async coroutine from a sync (scheduler thread) context."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


def _job_scrape():
    logger.info("Scheduled scrape starting")
    from .scraper import run_scrape
    _run_async(run_scrape())


def _job_weekly_report():
    logger.info("Sending weekly report")
    try:
        from .email_report import send_weekly_report
        send_weekly_report()
    except Exception as e:
        logger.error("Weekly report failed: %s", e)


def _job_daily_matches():
    logger.info("Sending daily matches email")
    try:
        from .email_report import send_daily_matches
        send_daily_matches()
    except Exception as e:
        logger.error("Daily matches email failed: %s", e)


def _parse_hm(time_str: str, default: str) -> tuple[str, str]:
    """Parse 'HH:MM' safely, falling back to default on malformed input."""
    try:
        h, m = time_str.split(":")
        int(h); int(m)  # validate numeric
        return h, m
    except Exception:
        logger.warning("Malformed time setting '%s', using default '%s'", time_str, default)
        h, m = default.split(":")
        return h, m


def start_scheduler():
    global _scheduler
    from .models import get_setting

    scrape_time = get_setting("scrape_time", "07:00")
    report_day = get_setting("report_day", "monday")
    report_time = get_setting("report_time", "08:00")

    scrape_h, scrape_m = _parse_hm(scrape_time, "07:00")
    report_h, report_m = _parse_hm(report_time, "08:00")

    _scheduler = BackgroundScheduler()

    # Daily scrape
    _scheduler.add_job(
        _job_scrape,
        CronTrigger(hour=scrape_h, minute=scrape_m),
        id="daily_scrape",
        replace_existing=True,
    )

    # Daily matches email — runs after scrape (scrape + 30min)
    daily_match_h = (int(scrape_h) + 1) % 24
    _scheduler.add_job(
        _job_daily_matches,
        CronTrigger(hour=daily_match_h, minute=scrape_m),
        id="daily_matches_email",
        replace_existing=True,
    )

    # Weekly report
    _scheduler.add_job(
        _job_weekly_report,
        CronTrigger(day_of_week=report_day[:3], hour=report_h, minute=report_m),
        id="weekly_report",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started — scrape at %s daily, report on %s at %s",
        scrape_time, report_day, report_time,
    )
    return _scheduler


def reschedule(scrape_time: str, report_day: str, report_time: str):
    """Update jobs after settings change — call from settings save."""
    global _scheduler
    if _scheduler is None:
        return
    scrape_h, scrape_m = _parse_hm(scrape_time, "07:00")
    report_h, report_m = _parse_hm(report_time, "08:00")
    daily_match_h = (int(scrape_h) + 1) % 24

    _scheduler.reschedule_job("daily_scrape", trigger=CronTrigger(hour=scrape_h, minute=scrape_m))
    _scheduler.reschedule_job("daily_matches_email", trigger=CronTrigger(hour=daily_match_h, minute=scrape_m))
    _scheduler.reschedule_job("weekly_report", trigger=CronTrigger(day_of_week=report_day[:3], hour=report_h, minute=report_m))
