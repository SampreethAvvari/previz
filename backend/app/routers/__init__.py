"""One router file per tab, auto-discovered.

This exists so that parallel branches never touch the same file. Adding a tab
means adding ONE new module in this package that exposes `router`. main.py is
never edited, so there is nothing to conflict on at merge time.

    # app/routers/mytab.py
    from fastapi import APIRouter
    router = APIRouter(prefix="/api/mytab", tags=["mytab"])

    @router.get("/")
    async def list_things(): ...

A module that fails to import is skipped with a warning rather than taking the
whole app down, so one broken branch cannot stop the demo.
"""
import importlib
import pkgutil

from fastapi import APIRouter, FastAPI


def discover() -> list[tuple[str, APIRouter]]:
    found = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  router {mod.name} failed to import, skipping: {exc}")
            continue
        r = getattr(m, "router", None)
        if isinstance(r, APIRouter):
            found.append((mod.name, r))
        else:
            print(f"  router {mod.name} has no `router` APIRouter, skipping")
    return found


def register_all(app: FastAPI) -> list[str]:
    names = []
    for name, r in discover():
        app.include_router(r)
        names.append(name)
    return names
