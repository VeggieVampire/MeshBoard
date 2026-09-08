import time

from location_service import distance_between_locations


menu_name = "Location"


def display_menu():
    return (
        "Location\n"
        "1. What's Here?\n"
        "2. Drop Note\n"
        "3. Nearby Notes\n"
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


def _render_location_detail(item, bbs_system):
    creator = item.get("creator_name") or bbs_system.db.display_name_for(item["creator_id"])
    lines = [
        f"Location ID {item['id']}",
        f"{int(item['distance'])} m away",
        f"By {creator}",
        _fmt_date(item["created_at"]),
        f"Lat {item['latitude']:.6f}",
        f"Lon {item['longitude']:.6f}",
    ]
    if item.get("altitude") not in (None, ""):
        lines.append(f"Alt {int(float(item['altitude']))} m")
    lines.extend(["", item["body"], "", "Reply BACK for the nearby list."])
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    state = _state(bbs_system, user_id)
    command_clean = command.strip()
    command_lower = command_clean.lower()

    if command_lower in ("menu", "back"):
        state.clear()
        state.update({"state": "menu", "page": 0, "nearby_results": []})
        return display_menu()

    if state["state"] == "await_note":
        if command_lower in ("cancel", "back", "menu", "next") or command_clean in ("1", "2", "3", "4", "5"):
            return "Still waiting for location note text. Send the note, or reply CANCEL."
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
        if command_lower == "back":
            return _render_nearby_page(state)
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
            return _render_location_detail(item, bbs_system)
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
                    "creator_id": row["creator_id"],
                    "creator_name": row["creator_name"],
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "altitude": row["altitude"],
                }
                for distance, row in nearby
            ]
            return _render_nearby_page(state)
        return "Invalid choice. Choose 1-3, or cd .. to return."

    state["state"] = "menu"
    return display_menu()
