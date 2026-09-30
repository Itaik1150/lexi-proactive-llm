"""
One-shot manual/testing entry point for the proactive cycle.

Scheduling in production is handled entirely by scheduler.py, which runs as a
persistent background service and fires run_full_proactive_cycle() according to
each experiment's dashboard-configured schedule (see Task 4.3/4.4).

This script is useful for manually triggering a single cycle on demand
(e.g. local testing, or a one-off run from a shell) — it does not run on
any timer itself.

Usage:
    cd logic-python
    python run_cycle.py
"""
import sys
import os

# Log lines contain emoji; a Windows console or pipe using cp1252 would crash on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Make sure imports resolve correctly when run from the repo root
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from services.research_service import research_service

if __name__ == "__main__":
    print("🚀 Manual trigger: starting proactive cycle...")
    result = research_service.run_full_proactive_cycle()
    if result.get("success"):
        r = result.get("results", {})
        print(f"✅ Done — FCM sent: {r.get('fcm_sent', 0)}, injected: {r.get('injected', 0)}")
        sys.exit(0)
    else:
        print(f"❌ Cycle failed: {result.get('message', 'unknown error')}")
        sys.exit(1)
