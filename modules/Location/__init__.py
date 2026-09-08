import time

from location_service import distance_between_locations
from modules.Games import hot_cold


menu_name = "Location"


def display_menu():
    return (
        "Location\n"
        "1. What's Here?\n"
        "2. Leave Something Here\n"
        "3. Nearby\n"
        "4. My Saved Locations\n"
        "5. Hot Cold\n"
        "cd .. - Back"
    )


def _fmt_date(timestamp):
    return time.strftime("%b %d, %Y", time.localtime(timestamp))


def _short_body(body, width=40):
    one_line = " ".join(body.split())
    if len(one_line) <= width:
        return one_line
    return one_line[: width - 3].rstrip() + "..."


def _state(bbs_system, user_id):
    user_state = bbs_system.users.setdefault(user_id, {"menu": ["main"]})
    return user_state.setdefault("location", {"state": "menu", "page": 0, "nearby_results": []})


def _nearby_rows(bbs_system, location, radius):
    rows = []
    for row in bbs_system.db.active_locations():
        distance = distance_between_locations(
            location["latitude"],
            location["longitude"],
            row["latitude"],
            row["longitude"],
        )
        if distance <= radius:
            rows.append((distance, row))
    return sorted(rows, key=lambda item: item[0])


def _render_whats_here(user_id, bbs_system):
    location, message = bbs_system.get_recent_location_or_message(user_id)
    if message:
        return message
    radius = bbs_system.config["gps"]["whats_here_radius_meters"]
    rows = _nearby_rows(bbs_system, location, radius)
    if not rows:
        return "Nothing has been saved near this location."
    lines = [f"{len(rows)} thing{'s' if len(rows) != 1 else ''} found nearby:"]
    for index, (distance, row) in enumerate(rows[:5], start=1):
        creator = row["creator_name"] or bbs_system.db.display_name_for(row["creator_id"])
        lines.append(f"{index}. {int(distance)} m away\n{creator} - {_fmt_date(row['created_at'])}\n\"{row['body']}\"")
    if len(rows) > 5:
        lines.append(f"Showing 1-5 of {len(rows)}. Use Nearby for more.")
    return "\n\n".join(lines)


def _render_nearby_page(state):
    rows = state.get("nearby_results", [])
    if not rows:
        return "Nothing has been saved nearby."
    page = state.get("page", 0)
    per_page = 5
    start = page * per_page
    end = min(start + per_page, len(rows))
    lines = [f"Nearby locations {start + 1}-{end} of {len(rows)}"]
    for index, item in enumerate(rows[start:end], start=start + 1):
        lines.append(f"{index}. {int(item['distance'])} m - {_short_body(item['body'])}")
    if end < len(rows):
        lines.append("Reply NEXT for more.")
    lines.append("Reply with a number to inspect.")
    return "\n".join(lines)


def _render_my_locations(user_id, bbs_system):
    rows = bbs_system.db.locations_by_creator(user_id)
    if not rows:
        return "You have not saved any locations yet."
    lines = ["My Saved Locations"]
    for index, row in enumerate(rows[:8], start=1):
        lines.append(f"{index}. ID {row['id']} - {_fmt_date(row['created_at'])} - {_short_body(row['body'])}")
    if len(rows) > 8:
        lines.append(f"Showing 1-8 of {len(rows)}.")
    lines.append("Reply VIEW <id> or DELETE <id>.")
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    state = _state(bbs_system, user_id)
    command_clean = command.strip()
    command_lower = command_clean.lower()

    if state["state"] == "hot_cold":
        if command_lower in ("menu", "back"):
            state["state"] = "menu"
            return display_menu()
        return hot_cold.process_command(user_id, command, bbs_system)

    if command_lower in ("menu", "back"):
        state.clear()
        state.update({"state": "menu", "page": 0, "nearby_results": []})
        return display_menu()

    if state["state"] == "await_note":
        if not command_clean:
            return "Message cannot be empty. Enter the message you want to leave at this location:"
        location, message = bbs_system.get_recent_location_or_message(user_id)
        if message:
            state["state"] = "menu"
            return message
        creator = bbs_system.db.display_name_for(user_id)
        bbs_system.db.save_location(
            user_id,
            creator if creator != user_id else None,
            location["latitude"],
            location["longitude"],
            location.get("altitude"),
            command_clean,
        )
        state["state"] = "menu"
        return "Saved at your current location."

    if state["state"] == "nearby":
        if command_lower == "next":
            if (state["page"] + 1) * 5 >= len(state.get("nearby_results", [])):
                return "No more nearby locations."
            state["page"] += 1
            return _render_nearby_page(state)
        try:
            selected = int(command_clean) - 1
        except ValueError:
            return _render_nearby_page(state)
        rows = state.get("nearby_results", [])
        if 0 <= selected < len(rows):
            item = rows[selected]
            return f"Location ID {item['id']}\n{int(item['distance'])} m away\n{_fmt_date(item['created_at'])}\n\n{item['body']}"
        return "Invalid location number."

    if state["state"] == "menu":
        if command_clean == "1":
            return _render_whats_here(user_id, bbs_system)
        if command_clean == "2":
            location, message = bbs_system.get_recent_location_or_message(user_id)
            if message:
                return message
            state["state"] = "await_note"
            return "Enter the message you want to leave at this location:"
        if command_clean == "3":
            location, message = bbs_system.get_recent_location_or_message(user_id)
            if message:
                return message
            radius = bbs_system.config["gps"]["nearby_radius_meters"]
            nearby = _nearby_rows(bbs_system, location, radius)
            state["state"] = "nearby"
            state["page"] = 0
            state["nearby_results"] = [
                {
                    "id": row["id"],
                    "distance": distance,
                    "body": row["body"],
                    "created_at": row["created_at"],
                }
                for distance, row in nearby
            ]
            return _render_nearby_page(state)
        if command_clean == "4":
            state["state"] = "my_locations"
            return _render_my_locations(user_id, bbs_system)
        if command_clean == "5":
            state["state"] = "hot_cold"
            return hot_cold.display_menu()
        return "Invalid choice. Choose 1-5, or cd .. to return."

    if state["state"] == "my_locations":
        parts = command_clean.split(maxsplit=1)
        if len(parts) == 2 and parts[0].lower() in ("view", "delete"):
            try:
                location_id = int(parts[1])
            except ValueError:
                return "Use VIEW <id> or DELETE <id>."
            if parts[0].lower() == "view":
                row = bbs_system.db.get_location_for_creator(location_id, user_id)
                if not row:
                    return "Location not found."
                return f"Location ID {row['id']}\n{_fmt_date(row['created_at'])}\n\n{row['body']}"
            if bbs_system.db.soft_delete_location(location_id, user_id):
                return "Location deleted."
            return "Location not found."
        return _render_my_locations(user_id, bbs_system)

    state["state"] = "menu"
    return display_menu()
