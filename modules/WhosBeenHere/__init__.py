import time


menu_name = "Who's Been Here"
PAGE_SIZE = 4


def display_menu():
    return "Who's Been Here\nShows recent MeshBoard users.\n1. Recent Users\ncd .. - Back"


def enter_menu(user_id, bbs_system):
    state = _seen_state(bbs_system, user_id)
    state["page"] = 0
    return _render_users(user_id, bbs_system)


def _seen_text(last_seen, now=None):
    now = int(now or time.time())
    age_seconds = max(0, now - int(last_seen))
    if age_seconds < 86400:
        return "Today"
    days = age_seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def _seen_state(bbs_system, user_id):
    user_state = bbs_system.users.setdefault(user_id, {"menu": ["main"]})
    return user_state.setdefault("seen", {"page": 0})


def _render_users(user_id, bbs_system):
    state = _seen_state(bbs_system, user_id)
    page = state.get("page", 0)
    offset = page * PAGE_SIZE
    users = bbs_system.db.recently_seen_users(PAGE_SIZE + 1, offset)
    if not users:
        return "No users yet.\ncd .. - Back"

    lines = ["Who's Been Here"]
    for row in users[:PAGE_SIZE]:
        name = bbs_system.db.display_name_for(row["node_id"])
        lines.append(f"{name:<10} Seen: {_seen_text(row['last_seen'])} Cmds: {row['command_count']}")
    if len(users) > PAGE_SIZE:
        lines.append("Next")
    lines.append("cd .. - Back")
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    state = _seen_state(bbs_system, user_id)
    command_lower = command.strip().lower()

    if command_lower in ("1", "recent", "users", "menu", "back"):
        state["page"] = 0
        return _render_users(user_id, bbs_system)
    if command_lower == "next":
        state["page"] = state.get("page", 0) + 1
        return _render_users(user_id, bbs_system)
    return _render_users(user_id, bbs_system)
