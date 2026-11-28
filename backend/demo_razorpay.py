"""Pays a student's transport fee end to end through Razorpay Checkout in TEST mode (no real money).

Visible Edge window: log in -> Pay now -> Razorpay Checkout -> contact number ->
Netbanking -> bank -> Razorpay's test bank page -> Success -> app verifies -> receipt.

Usage: python demo_razorpay.py <student_id> <screenshot_dir>   (server on :8000 with rzp_test_ keys)
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SID = sys.argv[1]
SHOTS = Path(sys.argv[2]); SHOTS.mkdir(parents=True, exist_ok=True)


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def frame_text(f):
    return " | ".join(t.strip() for t in f.locator("body").inner_text().splitlines() if t.strip())[:600]


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=False, slow_mo=250,
                                 args=["--window-position=200,0", "--window-size=1100,1000"])
    ctx = browser.new_context(viewport={"width": 1080, "height": 900})
    p = ctx.new_page()
    p.set_default_timeout(45000)

    log("login as student")
    p.goto(f"{BASE}/login")
    p.get_by_label("Student ID / Username").fill(SID)
    p.get_by_label("Password").fill("student123")
    p.get_by_role("button", name="Log in").click()
    p.get_by_role("button", name="Pay now").wait_for()
    p.screenshot(path=str(SHOTS / "r1_fee_card.png"))

    log("open Razorpay Checkout")
    p.get_by_role("button", name="Pay now").click()
    p.locator("iframe.razorpay-checkout-frame").wait_for()
    f = p.frame_locator("iframe.razorpay-checkout-frame")
    phone = f.locator("input[type=tel]").first
    phone.wait_for()
    time.sleep(1.5)
    p.screenshot(path=str(SHOTS / "r2_checkout.png"))

    log("enter test contact number")
    phone.fill("9876543210")
    f.get_by_test_id("contact-overlay-container").get_by_role("button", name="Continue").click()
    time.sleep(2.5)
    log("checkout now shows: " + frame_text(f))

    log("choose Netbanking")
    f.get_by_text("Netbanking", exact=True).first.click()
    time.sleep(2.5)
    p.screenshot(path=str(SHOTS / "r3_netbanking.png"))
    log("netbanking shows: " + frame_text(f))

    # pick a bank (first one offered), then pay -> Razorpay opens its test bank page in a popup
    bank = f.get_by_text("SBI", exact=False).first
    if not bank.count():
        bank = f.locator("[role=radio], label, button").filter(has_text="Bank").first
    bank.click()
    time.sleep(1.5)
    with ctx.expect_page(timeout=45000) as popup_info:
        pay = f.get_by_role("button", name="Pay Now")
        if not pay.count():
            pay = f.get_by_role("button").filter(has_text="Pay").last
        pay.click()
    bank_page = popup_info.value
    bank_page.wait_for_load_state()
    time.sleep(2)
    bank_page.screenshot(path=str(SHOTS / "r4_test_bank.png"))
    log("test bank page: " + bank_page.url[:90])

    log("click Success on Razorpay's test bank page")
    bank_page.get_by_role("button", name="Success").click()

    p.get_by_text("Payment successful").wait_for(timeout=60000)
    time.sleep(1.5)
    ref = p.get_by_role("dialog").locator(".receipt code").inner_text()
    p.screenshot(path=str(SHOTS / "r5_receipt.png"))
    log(f"PAID - receipt reference {ref}")
    time.sleep(6)  # leave it on screen for a moment
    browser.close()
