"""Operator surface for the AI kill switch.

    manage.py ai_feature list
    manage.py ai_feature set ddup.rank off --actor alice --reason "..."

Turning a feature off needs no approval and takes effect on the next call.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ai_services.models import AiFeature, FeatureCode, FeatureState
from apps.ai_services.services import (
    AiDisabledError,
    GateError,
    feature_state,
    master_enabled,
    set_feature_state,
)


class Command(BaseCommand):
    help = "List or change AI feature states (ADR-0045)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list")
        s = sub.add_parser("set")
        s.add_argument("code", choices=[c.value for c in FeatureCode])
        s.add_argument("state", choices=[s.value for s in FeatureState])
        s.add_argument("--actor", required=True)
        s.add_argument("--reason", required=True)

    def handle(self, *args, **opts):
        if opts["action"] == "list":
            self.stdout.write(f"AI_SERVICES_ENABLED={master_enabled()}")
            for code in FeatureCode.values:
                row = AiFeature.objects.filter(code=code).first()
                stored = row.state if row else "(no row)"
                self.stdout.write(f"{code}: stored={stored} effective={feature_state(code)}")
            return
        try:
            row = set_feature_state(opts["code"], opts["state"], actor=opts["actor"], reason=opts["reason"])
        except (AiDisabledError, GateError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{row.code} -> {row.state}")
