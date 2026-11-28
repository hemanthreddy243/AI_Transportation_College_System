"""Visible browser demo of fee payment + savings/payments tracking (two Edge windows).

Left window: admin. Right window: a student whose transport fee is pending.
Windows stay open afterwards. Usage (server on :8000):  python demo_payments.py <screenshot_dir>
"""
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://localhost:8000"
SHOTS = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
DATA = Path(__file__).parent / "data"
PAUSE = 2.5  # seconds to let a viewer read each screen


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    log(f"   screenshot {name}.png")


def launch_edge(port, x, profile):
    subprocess.Popen([EDGE, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
                      "--no-default-browser-check", f"--window-position={x},0", "--window-size=960,1040", "about:blank"])


def connect(pw, port):
    for _ in range(40):
        try:
            return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", slow_mo=350)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Edge did not start")


def login(page, user, pw):
    page.goto(f"{BASE}/login")
    page.evaluate("localStorage.clear()")
    page.goto(f"{BASE}/login")
    page.get_by_label("Student ID / Username").fill(user)
    page.get_by_label("Password").fill(pw)
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="Log out").wait_for()


def unpaid_student():
    reg = {r[0] for r in sqlite3.connect(DATA / "app.db").execute("SELECT username FROM users")}
    for sid, name in sqlite3.connect(DATA / "college.db").execute(
            "SELECT student_id, name FROM students WHERE fee_paid = 0 ORDER BY student_id"):
        if sid not in reg:
            return sid, name
    raise RuntimeError("no unpaid, unregistered student left - reset with: python -m app.seed --reset")


def main():
    tmp = SHOTS.parent
    launch_edge(9322, 0, tmp / "edge-pay-admin")
    launch_edge(9323, 960, tmp / "edge-pay-student")
    with sync_playwright() as pw:
        admin = connect(pw, 9322).contexts[0].pages[0]
        student = connect(pw, 9323).contexts[0].pages[0]
        for p in (admin, student):
            p.set_default_timeout(60000)

        log("1. Admin logs in and opens Savings")
        login(admin, "admin", "admin123")
        admin.get_by_role("button", name="💰 Savings").click()
        admin.get_by_text("diesel cost saved").wait_for()
        time.sleep(PAUSE)
        tiles = admin.locator(".tile").all_inner_texts()[:4]
        log("   savings: " + " | ".join(t.replace("\n", " ") for t in tiles))
        shot(admin, "p1_admin_savings")

        admin.get_by_role("button", name="🧾 Payments").click()
        admin.get_by_text("Recent online payments").wait_for()
        time.sleep(PAUSE)
        before = admin.locator(".tile").first.inner_text().replace("\n", " ")
        log(f"   payments before: {before}")
        shot(admin, "p2_admin_payments_before")

        log("   opening tomorrow's voting window so students can book seats")
        admin.get_by_role("button", name="🗺 Trips").click()
        now = datetime.now()
        admin.get_by_role("button", name="+ New voting window").click()
        admin.get_by_label("Trip date").fill((now + timedelta(days=1)).strftime("%Y-%m-%d"))
        admin.get_by_label("Voting opens").fill((now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M"))
        admin.get_by_label("Voting closes").fill((now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M"))
        admin.get_by_role("button", name="Schedule voting").click()
        admin.get_by_role("button", name="Close voting now").wait_for()

        sid, name = unpaid_student()
        log(f"2. Student {name} ({sid}) registers - fee is pending")
        student.bring_to_front()
        student.goto(f"{BASE}/login")
        student.evaluate("localStorage.clear()")
        student.goto(f"{BASE}/register")
        student.get_by_label("Student ID").fill(sid)
        student.get_by_label("Full name (as in college records)").fill(name)
        student.get_by_label("Password", exact=True).fill("student123")
        student.get_by_label("Confirm password").fill("student123")
        student.get_by_role("button", name="Register").click()
        student.get_by_role("button", name="Pay now").wait_for()
        time.sleep(PAUSE)
        shot(student, "p3_student_fee_pending")

        log("3. Student tries to book a seat -> blocked until fee is paid")
        student.get_by_role("button", name="✅ Yes, I'm coming").click()
        msg = student.locator(".alert.error").first
        msg.wait_for()
        msg.scroll_into_view_if_needed()
        log(f"   message: {msg.inner_text()}")
        time.sleep(PAUSE)

        log("4. Student pays (demo checkout, UPI)")
        student.get_by_role("button", name="Pay now").scroll_into_view_if_needed()
        student.get_by_role("button", name="Pay now").click()
        student.get_by_role("button", name="UPI").click()
        time.sleep(PAUSE)
        shot(student, "p4_checkout")
        student.get_by_role("button", name="(demo)").click()
        student.get_by_text("Payment successful").wait_for()
        time.sleep(PAUSE)
        ref = student.get_by_role("dialog").locator(".receipt code").inner_text()
        log(f"   receipt reference: {ref}")
        shot(student, "p5_receipt")
        student.get_by_role("button", name="Done").click()

        log("5. Student books a seat - now allowed")
        student.get_by_role("button", name="✅ Yes, I'm coming").click()
        student.get_by_text("Your answer:").wait_for()
        log(f"   fee badge: {student.locator('.profile .badge').inner_text()}")
        time.sleep(PAUSE)
        shot(student, "p6_student_paid_voted")

        log("6. Admin sees the payment")
        admin.bring_to_front()
        admin.reload()
        admin.get_by_role("button", name="🧾 Payments").click()
        admin.get_by_text("Recent online payments").wait_for()
        time.sleep(PAUSE)
        after = admin.locator(".tile").first.inner_text().replace("\n", " ")
        row = admin.locator("tbody tr").first.inner_text().replace("\t", " | ")
        log(f"   payments after: {after}")
        log(f"   newest payment: {row}")
        shot(admin, "p7_admin_payments_after")

        log("7. Other students vote, voting closes, routes are planned (savings recorded)")
        admin.get_by_role("button", name="🗺 Trips").click()
        admin.get_by_role("button", name="Simulate student votes (demo)").click()
        time.sleep(2)
        admin.get_by_role("button", name="Close voting now").click()
        time.sleep(2)
        admin.get_by_role("button", name="Plan routes & assign buses").click()
        admin.get_by_role("heading", name="Bus plan").wait_for(timeout=180000)
        time.sleep(4)
        log("   plan: " + " | ".join(t.replace("\n", " ") for t in admin.locator(".tile").all_inner_texts()[4:8]))
        shot(admin, "p8_admin_new_plan")

        admin.get_by_role("button", name="💰 Savings").click()
        admin.get_by_text("diesel cost saved").wait_for()
        time.sleep(PAUSE)
        trips_card = admin.locator("section.card").filter(has=admin.get_by_role("heading", name="Trips", exact=True))
        newest = trips_card.locator("tbody tr").first.inner_text().replace("\t", " | ")
        log(f"   today's trip added to savings: {newest}")
        shot(admin, "p9_admin_savings_after")
        admin.get_by_role("button", name="🗺 Trips").click()
        log("done - windows left open")


if __name__ == "__main__":
    main()
