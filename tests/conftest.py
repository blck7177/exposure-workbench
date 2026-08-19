"""Where the suite finds the things the app finds by other means.

One job today: the tool face. Inside compose the loops reach exposure-mcp by
service name, and that name is compose's to supply — it is deliberately absent
from .env, because anything set there is substituted into the containers as
well. The suite runs OUTSIDE the network, so it needs its own name for the same
face: the loopback port the mcp service publishes.

It has to happen here rather than in the live module that needs it. Settings is
a cached singleton built on first use, and pytest imports every collected module
before running anything — so whichever module calls get_settings() first decides
the URL for the whole session, and by the time a live test is running it is far
too late to say anything about it.
"""

from __future__ import annotations

import os

os.environ["MCP_URL"] = os.getenv("MCP_URL_LOCAL", "http://localhost:8104")
