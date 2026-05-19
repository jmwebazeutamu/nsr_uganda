"""Signal wiring: any change to a ChoiceList or ChoiceOption flushes
the resolver cache. Process-local — cross-process invalidation rides
on the bundle ETag (see apps.reference_data.api)."""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ChoiceList, ChoiceOption


@receiver([post_save, post_delete], sender=ChoiceList)
@receiver([post_save, post_delete], sender=ChoiceOption)
def _invalidate_resolver_cache(sender, **kwargs):
    # Local import keeps services importable without Django apps
    # ready during test collection.
    from .services import clear_resolver_cache
    clear_resolver_cache()
