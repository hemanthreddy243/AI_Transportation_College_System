"""Regenerates the README screenshots and live-tracking GIF from the running app.

Needs: server on :8000 with a published plan, and simulate_buses.py running.
Usage:  python capture_screens.py ../docs  [--student 22B81A661492]
"""
import sys
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright

OUT = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), "../docs"))
STUDENT = sys.argv[sys.argv.index("--student") + 1] if "--student" in sys.argv else "22B81A661492"
BASE = "http://localhost:8000"
OUT.mkdir(parents=True, exist_ok=True)


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def login(page, user, pw):
    page.goto(f"{BASE}/login")
    page.evaluate("localStorage.clear()")
    page.goto(f"{BASE}/login")
    page.get_by_label("Student ID / Username").fill(user)
    page.get_by_label("Password").fill(pw)
    page.get_by_role("button", name="Log in").click()
    page.get_by_role("button", name="Log out").wait_for()
    page.add_style_tag(content=".topbar{position:static !important}")  # keep it out of element shots


def card(page, text):
    return page.locator("section.card", has_text=text).first


def main():
    api = httpx.Client(base_url=f"{BASE}/api", timeout=30)
    tok = api.post("/auth/login", json={"username": STUDENT, "password": "student123"}).json()["token"]
    bus = api.get("/me/bus", headers={"Authorization": f"Bearer {tok}"}).json()
    bus_id, my_stop = bus["route"]["bus_id"], next(
        s for s in api.get("/me", headers={"Authorization": f"Bearer {tok}"}).json()["stop"].values() if isinstance(s, str) and s.startswith("S"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        desk = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        phone = browser.new_page(viewport={"width": 420, "height": 900}, device_scale_factor=2)
        for p in (desk, phone):
            p.set_default_timeout(60000)

        desk.goto(f"{BASE}/register")
        desk.evaluate("localStorage.clear()")
        desk.goto(f"{BASE}/register")
        desk.screenshot(path=str(OUT / "register.png"))
        log("register.png")

        # wait until every planned bus has left, so the fleet view shows buses on the road
        admin_tok = api.post("/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
        t0 = time.time()
        while time.time() - t0 < 300:
            states = [l["state"] for l in api.get("/admin/live", headers={"Authorization": f"Bearer {admin_tok}"}).json()]
            if states.count("not_started") == 0:
                break
            time.sleep(3)
        login(desk, "admin", "admin123")
        card(desk, "Students per stop").wait_for()
        time.sleep(3)
        card(desk, "Trip planning").screenshot(path=str(OUT / "admin_voting.png"))
        card(desk, "Students per stop").screenshot(path=str(OUT / "admin_stop_counts.png"))
        time.sleep(4)  # map tiles + live markers
        card(desk, "Bus plan").screenshot(path=str(OUT / "admin_plan_live.png"))
        card(desk, "AI briefing").screenshot(path=str(OUT / "admin_ai_briefing.png"))
        log("admin screenshots")

        login(desk, f"driver{bus_id}", "driver123")
        time.sleep(3)
        desk.screenshot(path=str(OUT / "driver.png"), full_page=True)
        log("driver.png")

        # Student on a phone: wait until their bus is on the way to their stop
        login(phone, STUDENT, "student123")
        t0 = time.time()
        while time.time() - t0 < 600:
            live = api.get("/me/bus", headers={"Authorization": f"Bearer {tok}"}).json()["live"]
            st = next((s for s in live["stops"] if s["id"] == my_stop), None)
            if live["state"] == "live" and st and st["status"] == "upcoming" and st.get("eta_min") and st["eta_min"] < 25:
                break
            time.sleep(2)
        phone.reload()
        where = card(phone, "Where is my bus?")
        where.wait_for()
        time.sleep(4)
        where.screenshot(path=str(OUT / "student_live.png"))
        log("student_live.png")

        frames = []
        for _ in range(24):  # ~48 s of live updates
            frames.append(Image.open(BytesIO(where.screenshot())).convert("RGB"))
            time.sleep(2)
        w = 360
        frames = [f.resize((w, int(f.height * w / f.width)), Image.LANCZOS).quantize(colors=96, method=Image.MEDIANCUT)
                  for f in frames]
        frames[0].save(OUT / "student_live.gif", save_all=True, append_images=frames[1:], duration=500, loop=0, optimize=True)
        log(f"student_live.gif ({(OUT / 'student_live.gif').stat().st_size // 1024} KB)")
        browser.close()


if __name__ == "__main__":
    main()
