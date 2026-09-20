"""
Proactive notification scheduler.

Runs as a persistent background service (e.g. a Render "Background Worker").
At startup, reads each enabled experiment's notification schedule
(experimentFeatures.proactiveSettings.schedule) from MongoDB and registers one
APScheduler job per configured fire time / random window, gated to that
experiment's own allowed days.

An hourly reload job re-reads the DB and updates all registered fire-time jobs
so that changes made in the Admin panel take effect within 60 minutes — no
Render restart required.

Falls back to a hardcoded default schedule if MongoDB is unreachable or no
experiment has proactive settings configured yet, so the service never fails
to start.

Usage:
    cd logic-python
    python scheduler.py

To stop: Ctrl+C
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR


def _has_firebase_credentials() -> bool:
    if os.getenv("SERVICE_ACCOUNT_JSON_CONTENT", "").strip():
        return True
    if (os.getenv("SERVICE_ACCOUNT_JSON") or "").strip().startswith("{"):
        return True
    for path in (
        "/etc/secrets/firebase.json",
        "/etc/secrets/service_account.json",
        "/etc/secrets/SERVICE_ACCOUNT_JSON_CONTENT",
    ):
        if os.path.isfile(path):
            return True
    return False


if _has_firebase_credentials():
    print("🔑 Firebase credentials detected")
else:
    print("❌ Firebase: no credentials found.")
    print("   On Render → Environment → add SERVICE_ACCOUNT_JSON_CONTENT")
    print("   (paste full JSON from lexi-72330-firebase-adminsdk-....json)")
    sys.exit(1)

from bson import ObjectId

from services.research_service import get_research_service
from utils.mongodb_client import mongodb_client

# ── Hardcoded fallback (used only if MongoDB is unreachable at startup, or no
#    experiment has a schedule configured yet) ─────────────────────────────────
FALLBACK_FIRE_TIMES = ["13:45", "17:30", "21:15"]
FALLBACK_ALLOWED_DAYS = [0, 1, 2, 3, 4, 5, 6]  # 0=Sun .. 6=Sat, all days

_DAY_ABBR = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _day_of_week_str(allowed_days) -> str:
    """Convert [0,1,4] (0=Sun) into APScheduler's 'sun,mon,thu' cron format."""
    days = sorted({d for d in (allowed_days or []) if isinstance(d, int) and 0 <= d <= 6})
    if not days or len(days) == 7:
        return "*"
    return ",".join(_DAY_ABBR[d] for d in days)


def load_schedules_from_db():
    """
    Read proactiveSettings.schedule from every experiment with proactive enabled.

    Returns a list of dicts, one per experiment:
      {"experiment_id": str, "allowed_days": [int], "mode": "exact"|"random",
       "fire_times": [str], "random_windows": [{"start": str, "end": str}]}

    Returns an empty list on any MongoDB failure — caller falls back to defaults.
    """
    schedules = []
    try:
        if not mongodb_client.connect():
            print("⚠️  Scheduler: could not connect to MongoDB — using fallback schedule")
            return []

        enabled_experiments = list(mongodb_client.db["experiments"].find(
            {"experimentFeatures.proactiveSettings.enabled": True},
            {"experimentFeatures.proactiveSettings.schedule": 1},
        ))

        for exp in enabled_experiments:
            ps = (exp.get("experimentFeatures") or {}).get("proactiveSettings") or {}
            sched = ps.get("schedule") or {}
            schedules.append({
                "experiment_id":  str(exp["_id"]),
                "allowed_days":   sched.get("allowedDays") or FALLBACK_ALLOWED_DAYS,
                "mode":           sched.get("mode") or "exact",
                "fire_times":     sched.get("fireTimes") or FALLBACK_FIRE_TIMES,
                "random_windows": sched.get("randomWindows") or [],
            })

    except Exception as e:
        print(f"⚠️  Scheduler: error loading schedules from MongoDB: {e}")
        return []
    finally:
        try:
            mongodb_client.disconnect()
        except Exception:
            pass

    return schedules


def proactive_job():
    """
    Runs the full proactive cycle across ALL enabled experiments' users.

    Per-user day-of-week enforcement happens inside coordinated_send_and_inject()
    (each user is gated by their OWN experiment's allowedDays) — this job-level
    day_of_week filter is a coarse pre-filter so we don't even attempt a cycle
    on days when nobody could possibly be eligible.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n⏰ [{now_str}] Scheduled proactive cycle triggered")

    try:
        result = get_research_service().run_full_proactive_cycle()
        if result.get("success"):
            r = result.get("results", {})
            print(f"✅ Cycle done — FCM sent: {r.get('fcm_sent', 0)}, injected: {r.get('injected', 0)}")
        else:
            print(f"⚠️  Cycle finished with issues: {result.get('message', 'unknown')}")
    except Exception as e:
        print(f"❌ Unhandled error in proactive_job: {e}")


def job_listener(event):
    if event.exception:
        print(f"❌ Scheduler job raised an exception: {event.exception}")


def _print_next_runs(scheduler: BlockingScheduler):
    """Print the next scheduled run time for each registered job."""
    jobs = [j for j in scheduler.get_jobs() if not j.id.startswith("heartbeat") and j.id != "reload_schedules"]
    if not jobs:
        print("   (no proactive jobs registered)")
        return
    for job in jobs:
        nrt = job.next_run_time
        nrt_str = nrt.strftime("%Y-%m-%d %H:%M %Z") if nrt else "unknown"
        print(f"   {job.id:<50} → next: {nrt_str}")


def reload_schedules(scheduler: BlockingScheduler):
    """
    Re-read experiment schedules from MongoDB and update APScheduler jobs in-place.
    Removes all experiment-specific proactive_ jobs, then re-registers from DB.
    Called automatically every hour so Admin-panel changes take effect without a restart.
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    print(f"\n🔄 [{now_str}] Reloading schedules from MongoDB…")

    new_schedules = load_schedules_from_db()

    # Remove all experiment-specific proactive jobs (keep fallback and system jobs)
    for job in scheduler.get_jobs():
        if job.id.startswith("proactive_") and not job.id.startswith("proactive_fallback_"):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass

    if new_schedules:
        registered = register_jobs(scheduler, new_schedules)
        print(f"🔄 Reload complete: {len(new_schedules)} experiment(s), {registered} job(s) registered")
    else:
        print("🔄 Reload: no enabled experiments — fallback jobs unchanged")

    _print_next_runs(scheduler)


def heartbeat():
    """Emitted every 30 minutes so Render logs confirm the scheduler process is alive."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"💓 [{now_str}] Scheduler heartbeat — process alive", flush=True)


def _get_experiment_users(experiment_id: str) -> list:
    """Return all eligible proactive users (isProactive=True, have FCM token) for one experiment."""
    try:
        if not mongodb_client.connect():
            return []
        id_variants = [experiment_id, ObjectId(experiment_id)]
        users = list(mongodb_client.db["users"].find({
            "experimentId":  {"$in": id_variants},
            "fcmToken":      {"$exists": True, "$ne": ""},
            "isProactive":   True,
        }))
        return users
    except Exception as e:
        print(f"⚠️  _get_experiment_users({experiment_id[:8]}): {e}")
        return []
    finally:
        try:
            mongodb_client.disconnect()
        except Exception:
            pass


def _run_single_user_proactive(user_id: str):
    """Per-user proactive cycle triggered by AI-scheduled date jobs."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n⏰ [{now_str}] AI-scheduled cycle for user {user_id[:8]}")
    try:
        get_research_service().run_single_user_cycle(user_id)
    except Exception as e:
        print(f"❌ _run_single_user_proactive({user_id[:8]}): {e}")


def ai_daily_planner_job(scheduler: BlockingScheduler, experiment_id: str, window: dict, count: int):
    """
    Runs at 00:01 Jerusalem time on each allowed day for experiments using mode='ai_agent'.

    For every eligible user in the experiment:
      1. Calls research_service.plan_ai_schedule() which queries the user's activity
         data and asks the LLM to pick `count` optimal HH:MM times within `window`.
      2. Registers a per-user APScheduler date-trigger job at each chosen time.

    Uses the 'ai_timed_' job-id prefix so the hourly reload_schedules pass does NOT
    accidentally remove these ephemeral same-day jobs.
    
    Respects maxDailyNotifications: caps count to the experiment's daily limit to
    avoid scheduling more notifications than allowed.
    """
    tz = ZoneInfo("Asia/Jerusalem")
    now_tz   = datetime.now(tz)
    now_str  = now_tz.strftime("%H:%M:%S")
    window_start = window.get("start", "16:00")
    window_end   = window.get("end",   "20:00")
    
    # Load maxDailyNotifications from experiment settings and cap count if needed
    effective_count = count
    try:
        if mongodb_client.connect():
            exp_doc = mongodb_client.db["experiments"].find_one(
                {"_id": ObjectId(experiment_id)},
                {"experimentFeatures.proactiveSettings.maxDailyNotifications": 1}
            )
            if exp_doc:
                ps = (exp_doc.get("experimentFeatures") or {}).get("proactiveSettings") or {}
                max_daily = ps.get("maxDailyNotifications")
                if max_daily and max_daily > 0 and max_daily < count:
                    effective_count = max_daily
                    print(f"   ⚠️  Count capped to maxDailyNotifications: {count} → {effective_count}")
    except Exception as e:
        print(f"   ⚠️  Could not load maxDailyNotifications for experiment {experiment_id[:8]}: {e}")
    finally:
        try:
            mongodb_client.disconnect()
        except Exception:
            pass

    print(f"\n🤖 [{now_str}] AI daily planner — experiment {experiment_id[:8]} "
          f"window={window_start}–{window_end} count={effective_count}")

    try:
        users = _get_experiment_users(experiment_id)
        if not users:
            print(f"   ⚠️  No eligible users for experiment {experiment_id[:8]}")
            return

        rs = get_research_service()
        registered = 0

        for user in users:
            user_id  = str(user["_id"])
            username = user.get("username", "Unknown")
            try:
                planned_times = rs.plan_ai_schedule(user, window_start, window_end, effective_count)
                for t_str in planned_times:
                    h, m = map(int, t_str.split(":"))
                    run_dt = now_tz.replace(hour=h, minute=m, second=0, microsecond=0)
                    if run_dt <= now_tz:
                        print(f"   ⏭️  [{username}] {t_str} is already past — skipping")
                        continue
                    job_id = f"ai_timed_{experiment_id}_{user_id}_{t_str.replace(':', '')}"
                    scheduler.add_job(
                        lambda uid=user_id: _run_single_user_proactive(uid),
                        "date",
                        run_date=run_dt,
                        id=job_id,
                        replace_existing=True,
                    )
                    print(f"   ✅ [{username}] → {t_str}")
                    registered += 1
            except Exception as e:
                print(f"   ❌ [{username}] planning failed: {e}")

        print(f"🤖 AI planner done: {registered} job(s) for {len(users)} user(s)")
    except Exception as e:
        print(f"❌ ai_daily_planner_job: {e}")


def register_jobs(scheduler: BlockingScheduler, schedules) -> int:
    """
    Register one APScheduler job per (experiment, fire_time) or
    (experiment, random_window) pair. Returns the number of jobs registered.
    """
    job_count = 0

    for sched in schedules:
        exp_id = sched["experiment_id"]
        dow = _day_of_week_str(sched["allowed_days"])

        if sched["mode"] == "ai_agent" and sched["random_windows"]:
            # Register ONE daily planner cron job at 00:01. It will query each user's
            # activity data, call the LLM, and register per-user date-trigger jobs.
            window = sched["random_windows"][0]
            count  = max(1, int(window.get("count") or 1))
            job_id = f"proactive_{exp_id}_ai_planner"
            scheduler.add_job(
                lambda s=scheduler, eid=exp_id, w=window, c=count: ai_daily_planner_job(s, eid, w, c),
                "cron",
                day_of_week=dow, hour=0, minute=1,
                id=job_id, replace_existing=True,
            )
            job_count += 1
            print(f"   🤖 AI planner job [{job_id}]: daily 00:01 ({dow}), "
                  f"window={window.get('start')}–{window.get('end')}, count={count}")

        elif sched["mode"] == "random" and sched["random_windows"]:
            for w_idx, window in enumerate(sched["random_windows"]):
                try:
                    start_h, start_m = map(int, window["start"].split(":"))
                    end_h, end_m = map(int, window["end"].split(":"))
                except (KeyError, ValueError):
                    print(f"⚠️  Skipping malformed random window for experiment {exp_id[:8]}: {window}")
                    continue
                window_seconds = max(
                    0, (end_h * 3600 + end_m * 60) - (start_h * 3600 + start_m * 60)
                )
                # Task 6.4: register `count` separate jobs per window so multiple
                # notifications can be distributed within the same time range.
                # Each job uses jitter to fire at a distinct random minute.
                count = max(1, int(window.get("count") or 1))
                for n in range(count):
                    job_id = f"proactive_{exp_id}_rand{w_idx}_{n}"
                    scheduler.add_job(
                        proactive_job, "cron",
                        day_of_week=dow, hour=start_h, minute=start_m,
                        jitter=window_seconds if window_seconds > 0 else None,
                        id=job_id, replace_existing=True,
                    )
                    job_count += 1
                print(f"   🎲 Registered {count} random job(s) in window "
                      f"{window['start']}–{window['end']} for experiment {exp_id[:8]} "
                      f"({dow}), jitter={window_seconds}s")
        else:
            # Task 6.4: no cap on exact fire times (previously capped at 3)
            for time_str in sched["fire_times"]:
                try:
                    h, m = map(int, time_str.split(":"))
                except ValueError:
                    print(f"⚠️  Skipping malformed fire time for experiment {exp_id[:8]}: {time_str}")
                    continue
                job_id = f"proactive_{exp_id}_{time_str.replace(':', '')}"
                scheduler.add_job(
                    proactive_job, "cron",
                    day_of_week=dow, hour=h, minute=m,
                    id=job_id, replace_existing=True,
                )
                print(f"   ⏰ Exact-time job [{job_id}]: {time_str} ({dow})")
                job_count += 1

    return job_count


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="Asia/Jerusalem")

    print("=" * 60)
    print("🗓️  Lexi Proactive Scheduler")
    print(f"   Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    schedules = load_schedules_from_db()

    if schedules:
        print(f"📡 Loaded schedule(s) from MongoDB for {len(schedules)} enabled experiment(s)")
        registered = register_jobs(scheduler, schedules)
    else:
        print("⚠️  No experiment schedules found — using hardcoded fallback")
        print(f"   Fire times : {', '.join(FALLBACK_FIRE_TIMES)} (Jerusalem time, all days)")
        for time_str in FALLBACK_FIRE_TIMES:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(proactive_job, "cron", hour=h, minute=m, id=f"proactive_fallback_{time_str}")
        registered = len(FALLBACK_FIRE_TIMES)

    # Reload schedules from MongoDB every hour so Admin-panel changes take effect
    # without needing a Render restart.
    scheduler.add_job(
        lambda: reload_schedules(scheduler),
        "cron", minute=0,
        id="reload_schedules", replace_existing=True,
    )

    # Heartbeat every 30 minutes — visible in Render logs to confirm the process is alive.
    scheduler.add_job(
        heartbeat, "interval", minutes=30,
        id="heartbeat", replace_existing=True,
    )

    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    print("=" * 60)
    print(f"   Proactive jobs registered : {registered}")
    print(f"   Schedule reload           : every hour (top of the hour)")
    print(f"   Heartbeat                 : every 30 min")
    print(f"   Per-user day-of-week + heuristic weights re-verified live every cycle")
    print("   Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        scheduler.start()  # blocks here; next_run_time is only available after start
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Scheduler stopped.")
