"""AnalyticsReplicaRouter — route DATA-EXP reads to the analytics
replica; forbid writes to its own app models (catalogue is metadata-
driven and writes come from the loader, which runs against `default`).

ADR-0023 D2:
- Reads from apps.data_explorer.* go to `analytics_replica` when the
  alias is configured. In dev/test the alias defaults to `default` so
  the router is effectively a no-op.
- Writes against managed apps.data_explorer.* models stay on `default`
  (the loader, dual-approval flow, and throttle counters are write
  paths). Matview-backed (managed=False) models reject writes.
"""

from __future__ import annotations

_REPLICA_ALIAS = "analytics_replica"


class AnalyticsReplicaRouter:
    """Route reads to the analytics replica; block writes against
    matview-backed unmanaged models."""

    app_label = "data_explorer"

    def _is_data_explorer(self, model) -> bool:
        return getattr(model._meta, "app_label", "") == self.app_label

    def db_for_read(self, model, **hints):
        if not self._is_data_explorer(model):
            return None
        # Honour the replica alias when present and distinct from
        # `default`. When the two aliases point at the same underlying
        # database (dev / test default), routing reads through the
        # replica alias only complicates the FK-assignment story
        # because Django treats the aliases as separate connections.
        # Use `default` in that case so model relations stay valid.
        from django.conf import settings
        dbs = getattr(settings, "DATABASES", {})
        if _REPLICA_ALIAS in dbs:
            default_cfg = dbs.get("default", {})
            replica_cfg = dbs[_REPLICA_ALIAS]
            same_db = (
                default_cfg.get("ENGINE") == replica_cfg.get("ENGINE")
                and default_cfg.get("NAME") == replica_cfg.get("NAME")
                and default_cfg.get("HOST", "") == replica_cfg.get("HOST", "")
                and default_cfg.get("PORT", "") == replica_cfg.get("PORT", "")
            )
            if not same_db:
                return _REPLICA_ALIAS
        return "default"

    def db_for_write(self, model, **hints):
        if not self._is_data_explorer(model):
            return None
        # Unmanaged (matview-backed) models: writes are forbidden by
        # contract. Return a sentinel value Django can't use → the
        # ORM raises rather than corrupting the matview.
        if not getattr(model._meta, "managed", True):
            # Returning None lets Django fall through to the default
            # router; we raise explicitly so the misuse is loud.
            raise RuntimeError(
                f"writes forbidden against unmanaged matview model "
                f"{model._meta.label}"
            )
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # The analytics replica is the same logical database as
        # `default` (it's a replica). When both objects belong to
        # data_explorer or are otherwise from analytics_replica/default,
        # the FK relation is legal. Other relations fall through to
        # Django's default policy.
        ok = {"default", _REPLICA_ALIAS}
        if obj1._state.db in ok and obj2._state.db in ok:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Migrations for DATA-EXP managed models run on `default`
        # (the catalogue tables). Matview-backed models are
        # managed=False so Django skips them.
        if app_label == self.app_label and db != "default":
            return False
        return None
