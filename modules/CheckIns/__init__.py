import time


menu_name = "Check-Ins"


def display_menu():
    return (
        "Check-Ins\n"
        "Shows recent location check-ins.\n"
        "1. Recent Check-Ins\n"
        "cd .. - Back"
    )


def enter_menu(user_id, bbs_system):
    return _render_checkins(bbs_system)


def _fmt_time(timestamp):
    return time.strftime("%b %d %H:%M", time.localtime(timestamp))


def _short_body(body, width=28):
    body = "" if body is None else " ".join(str(body).split())
    if len(body) <= width:
        return body
    return body[: width - 3].rstrip() + "..."


def _render_checkins(bbs_system):
    rows = bbs_system.db.location_checkins(8)
    if not rows:
        return (
            "Check-Ins\n"
            "No location check-ins yet.\n"
            "Use Location > Check In to add yours.\n"
            "cd .. - Back"
        )

    lines = ["Recent Location Check-Ins"]
    for index, row in enumerate(rows, start=1):
        name = row["creator_name"] or bbs_system.db.display_name_for(row["creator_id"])
        lines.append(f"{index}. {name} - {_fmt_time(row['created_at'])} - {_short_body(row['body'])}")
    lines.append("Use Location > Check In to add yours. cd .. - Back")
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    return _render_checkins(bbs_system)
