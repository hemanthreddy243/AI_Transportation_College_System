import os

# Keep tests fast and offline: straight-line distances instead of calling the OSRM server.
os.environ.setdefault("ROUTING_PROVIDER", "straight")

# Tests must not pick up real Razorpay keys from backend/.env: demo checkout unless a test enables it.
for _k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
    os.environ[_k] = ""
