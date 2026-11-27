"""Re-plan in the already-open demo Edge windows and show road routes + driving bus.

Usage: python demo_replan.py <screenshot_dir>    (run demo_browser.py first)
"""
import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")
SHOTS.mkdir(parents=True, exist_ok=True)
DATA = Path(__file__).parent / "data"


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    log(f"screenshot {name}.png")


with sync_playwright() as pw:
    a = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    s = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    admin = next(p for p in a.contexts[0].pages if p.url.startswith("http://localhost"))
    student = next(p for p in s.contexts[0].pages if p.url.startswith("http://localhost"))
    driver = next((p for p in a.contexts[0].pages if p.url.startswith("http://127.0.0.1")), None)
    for p in (admin, student):
        p.set_default_timeout(120000)

    if driver:  # stop the old straight-line drive
        driver.reload()

    log("admin: re-plan with real road distances")
    admin.bring_to_front()
    admin.reload()
    admin.get_by_role("button", name="Re-plan routes").click()
    admin.get_by_text("real roads (OSRM)").wait_for()
    time.sleep(4)
    shot(admin, "10_admin_road_plan")
    log("routes: " + " | ".join(t.replace("\n", " ") for t in admin.locator(".route-card").all_inner_texts()))

    student.reload()
    student.locator(".bus-number").wait_for()
    bus_number = student.locator(".bus-number").inner_text()
    bus_id = sqlite3.connect(DATA / "app.db").execute("SELECT id FROM buses WHERE number=?", (bus_number,)).fetchone()[0]
    log(f"student now on {bus_number} -> driver{bus_id}")

    if driver is None:
        driver = a.contexts[0].new_page()
    driver.set_default_timeout(60000)
    driver.goto("http://127.0.0.1:8000/login")
    if driver.get_by_role("button", name="Log out").count():
        driver.get_by_role("button", name="Log out").click()
    driver.get_by_label("Student ID / Username").fill(f"driver{bus_id}")
    driver.get_by_label("Password").fill("driver123")
    driver.get_by_role("button", name="Log in").click()
    driver.get_by_role("button", name="Simulate drive (demo)").click()
    time.sleep(3)
    shot(driver, "11_driver_road_drive")

    student.bring_to_front()
    time.sleep(20)
    shot(student, "12_student_bus_on_road")
    time.sleep(20)
    shot(student, "13_student_bus_on_road_later")
    log("done")
