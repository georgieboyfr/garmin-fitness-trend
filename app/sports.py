"""Types d'activité Garmin (activityType.typeKey) comptés comme course à pied.

Toutes les activités sont synchronisées, mais seules celles-ci entrent dans les
statistiques et la charge d'entraînement.
"""

RUNNING_TYPES = frozenset({
    "running",
    "trail_running",
    "treadmill_running",
    "indoor_running",
    "track_running",
    "street_running",
    "ultra_run",
    "obstacle_run",
    "virtual_run",
})


def is_running(activity_type: str | None) -> bool:
    return activity_type in RUNNING_TYPES
