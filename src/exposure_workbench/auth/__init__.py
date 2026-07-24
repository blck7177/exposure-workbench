"""Identity (V2-A). Clerk session-token verification + the current-user context.

The ONLY auth code in the backend. Login, OAuth, sessions and password storage
are entirely Clerk's; here we only verify a Clerk-issued JWT and expose who the
request is for. See docs/IMPLEMENTATION_PLAN_V2.md V2-A.
"""
