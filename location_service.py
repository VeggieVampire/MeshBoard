import math
import time


def distance_between_locations(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between latitude/longitude pairs."""
    radius_meters = 6371e3
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_meters * c


def location_age(location, now=None):
    if not location:
        return None
    now = now or time.time()
    return max(0, now - location.get("received_at", location.get("timestamp", now)))


def format_location_age(age_seconds):
    if age_seconds is None:
        return "unknown"
    if age_seconds < 60:
        return f"{int(age_seconds)} seconds"
    minutes = int(age_seconds // 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = int(minutes // 60)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def stale_location_message(age_seconds):
    age_text = format_location_age(age_seconds)
    return (
        f"Your last GPS position is {age_text} old.\n"
        "Wait for your node to send a new position update and try again."
    )
