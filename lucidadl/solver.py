"""Fork-only: get the Cloudflare clearance from a FlareSolverr-compatible service.

Works with FlareSolverr and Byparr (same ``POST /v1`` ``request.get`` API). Point
``[Lucida] solver_url`` at one that runs on the same network (same public IP) as lucidarr:
``cf_clearance`` is tied to IP + user agent, and the user agent the solver reports is the
one we must send with the cookie, so both are saved together.

``install`` swaps the browser-based ``acquire_clearance`` in ``cli`` for a solver-backed one.
cli.py looks that name up at call time, so no upstream file needs editing.
"""

from __future__ import annotations

from typing import Optional, Tuple

LUCIDA_URL = "https://lucida.to"


class SolverError(RuntimeError):
    pass


async def solve(solver_url: str, timeout: float = 90.0,
                target: str = LUCIDA_URL) -> Tuple[Optional[str], str]:
    """Ask the solver to clear ``target``; return (cf_clearance or None, user agent)."""
    import httpx

    endpoint = solver_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    body = {"cmd": "request.get", "url": target, "maxTimeout": int(timeout * 1000)}
    try:
        async with httpx.AsyncClient(timeout=timeout + 30) as http:
            r = await http.post(endpoint, json=body)
    except httpx.HTTPError as e:
        raise SolverError(f"solver unreachable at {endpoint}: {e}") from e
    try:
        data = r.json()
    except ValueError:
        raise SolverError(f"solver answered HTTP {r.status_code} without JSON "
                          f"({r.text[:120]!r}); see its log") from None
    if data.get("status") != "ok":
        raise SolverError(f"solver did not clear {target}: {data.get('message') or r.status_code}")
    sol = data.get("solution") or {}
    ua = sol.get("userAgent")
    if not ua:
        raise SolverError("solver returned no user agent")
    cf = next((c.get("value") for c in sol.get("cookies") or []
               if c.get("name") == "cf_clearance"), None)
    return cf, ua


def install(solver_url: str, timeout: float = 90.0) -> None:
    """Make every clearance (re)acquire in this process go through the solver."""
    from . import cli as _base
    from . import session

    async def acquire_via_solver(hidden: bool = False):
        cf, ua = await solve(solver_url, timeout)
        session.save_clearance(cf, ua)
        return cf, ua

    _base.acquire_clearance = acquire_via_solver
