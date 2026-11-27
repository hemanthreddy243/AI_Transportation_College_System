import os

# Keep tests fast and offline: straight-line distances instead of calling the OSRM server.
os.environ.setdefault("ROUTING_PROVIDER", "straight")
