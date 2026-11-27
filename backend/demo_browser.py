"""Drives the whole app in two visible Edge windows (admin+driver, student).

Edge is started separately with remote debugging, so the windows stay open after this script ends.
Usage (server running on :8000):  python demo_browser.py <screenshot_dir>
"""
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SHOTS = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
DATA = Path(__file__).parent / "data"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def launch_edge(port, x, profile):
    subprocess.Popen([
        EDGE, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check", f"--window-position={x},0", "--window-size=960,1040",
        "about:blank",
    ])


def connect(pw, port):
    for _ in range(40):
        try:
            return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Edge on port {port} did not start")


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    log(f"screenshot {name}.png")


def login(page, base, user, pw):
    page.goto(f"{base}/login")
    page.evaluate("localStorage.clear()")  # forget any login saved from an earlier run
    page.goto(f"{base}/login")
    page.get_by_label("Student ID / Username").fill(user)
    page.get_by_label("Password").fill(pw)
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="Log out").wait_for()


def pick_new_student():
    registered = {r[0] for r in sqlite3.connect(DATA / "app.db").execute("SELECT username FROM users")}
    for sid, name, fee in sqlite3.connect(DATA / "college.db").execute(
            "SELECT student_id, name, fee_paid FROM students ORDER BY student_id DESC"):
        if fee and sid not in registered:
            return sid, name
    raise RuntimeError("no unregistered student left")


def main():
    tmp = SHOTS.parent
    resume = "--resume" in sys.argv
    if not resume:
        launch_edge(9222, 0, tmp / "edge-admin")
        launch_edge(9223, 960, tmp / "edge-student")
    with sync_playwright() as pw:
        admin_browser, student_browser = connect(pw, 9222), connect(pw, 9223)
        admin = admin_browser.contexts[0].pages[0]
        student = student_browser.contexts[0].pages[0]
        for p in (admin, student):
            p.set_default_timeout(60000)

        if resume:
            admin = next(p for p in admin_browser.contexts[0].pages if "localhost" in p.url)
            student = next(p for p in student_browser.contexts[0].pages if "localhost" in p.url)
        else:
            run_setup(admin, student)
        if "--setup-only" not in sys.argv:
            finish(admin_browser, admin, student)


def run_setup(admin, student):
        # 1. Admin opens a voting window for tomorrow
        log("admin: login + schedule voting window")
        login(admin, "http://localhost:8000", "admin", "admin123")
        now = datetime.now()
        admin.get_by_role("button", name="+ New voting window").click()
        admin.get_by_label("Trip date").fill((now + timedelta(days=1)).strftime("%Y-%m-%d"))
        admin.get_by_label("Voting opens").fill((now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M"))
        admin.get_by_label("Voting closes").fill((now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))
        admin.get_by_role("button", name="Schedule voting").click()
        admin.get_by_text("open", exact=True).first.wait_for()
        shot(admin, "01_admin_voting_open")

        # 2. A new student registers (checked against college DB) and votes Yes
        sid, name = pick_new_student()
        log(f"student: register {sid} ({name}) and vote yes")
        student.goto("http://localhost:8000/login"); student.evaluate("localStorage.clear()")
        student.goto("http://localhost:8000/register")
        student.get_by_label("Student ID").fill(sid)
        student.get_by_label("Full name (as in college records)").fill(name)
        student.get_by_label("Password", exact=True).fill("student123")
        student.get_by_label("Confirm password").fill("student123")
        shot(student, "02_student_register")
        student.get_by_role("button", name="Register").click()
        student.get_by_role("button", name="Log out").wait_for()
        student.get_by_role("button", name="✅ Yes, I'm coming").click()
        student.get_by_text("Your answer:").wait_for()
        shot(student, "03_student_voted_yes")

        # 3. Admin: other students vote, voting closes, agent plans routes
        log("admin: simulate votes, close voting, plan routes")
        admin.get_by_role("button", name="Simulate student votes (demo)").click()
        time.sleep(2)
        admin.get_by_role("button", name="Close voting now").click()
        time.sleep(2)
        admin.get_by_role("button", name="Plan routes & assign buses").click()
        admin.get_by_role("heading", name="Bus plan").wait_for(timeout=120000)
        time.sleep(3)  # map tiles
        shot(admin, "04_admin_plan")


def finish(admin_browser, admin, student):

        # 4. Student sees the assigned bus
        student.reload()
        student.locator(".bus-number").wait_for()
        bus_number = student.locator(".bus-number").inner_text()
        log(f"student assigned to bus {bus_number}")
        bus_id = sqlite3.connect(DATA / "app.db").execute(
            "SELECT id FROM buses WHERE number = ?", (bus_number,)).fetchone()[0]

        # 5. Driver of that bus (new tab, different origin = separate login) starts the drive
        log(f"driver{bus_id}: login")
        driver = admin_browser.contexts[0].new_page()
        driver.set_default_timeout(60000)
        login(driver, "http://127.0.0.1:8000", f"driver{bus_id}", "driver123")
        if "--no-sim" not in sys.argv:  # otherwise simulate_buses.py is driving
            driver.get_by_role("button", name="Simulate drive (demo)").click()
        time.sleep(4)
        shot(driver, "05_driver_driving")

        student.bring_to_front()
        student.locator(".bus-number").scroll_into_view_if_needed()
        time.sleep(12)
        shot(student, "06_student_live_bus")
        time.sleep(15)
        shot(student, "07_student_live_bus_later")
        log("done - windows left open, bus keeps driving")


if __name__ == "__main__":
    main()
