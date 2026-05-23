"""Signal wiring for the reference_data app.

1. Any change to ChoiceList or ChoiceOption flushes the resolver
   cache. Process-local — cross-process invalidation rides on the
   bundle ETag (see apps.reference_data.api).
2. Any change to GeographicUnit re-derives the parent's
   children_count_cached so the Admin Console drill view stays
   honest without an expensive COUNT(*).
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ChoiceList, ChoiceOption, GeographicUnit


@receiver([post_save, post_delete], sender=ChoiceList)
@receiver([post_save, post_delete], sender=ChoiceOption)
def _invalidate_resolver_cache(sender, **kwargs):
    # Local import keeps services importable without Django apps
    # ready during test collection.
    from .services import clear_resolver_cache
    clear_resolver_cache()


@receiver([post_save, post_delete], sender=GeographicUnit)
def _refresh_children_count(sender, instance, **kwargs):
    """Keep children_count_cached on the parent in sync with the
    actual row count. Fires on every save / delete; the count is
    cheap (one indexed lookup on parent_id)."""
    if instance.parent_id is None:
        return
    # Local import avoids a circular dep at app-loading time.
    from .lifecycle import recompute_children_count
    recompute_children_count(instance.parent_id)
