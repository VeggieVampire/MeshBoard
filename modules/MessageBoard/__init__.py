import time


menu_name = "Message Board"
PAGE_SIZE = 6

CATEGORIES = [
    ("general", "General Discussion"),
    ("news", "Local News"),
    ("trade", "Buy / Sell / Trade"),
    ("events", "Events"),
    ("rumors", "Rumors & Gossip"),
    ("header", "Main Menu Header"),
]


def display_menu():
    lines = ["Message Board"]
    for index, (_, label) in enumerate(CATEGORIES, start=1):
        lines.append(f"{index}. {label}")
    lines.append("cd .. - Back")
    return "\n".join(lines)


def _board_state(bbs_system, user_id):
    user_state = bbs_system.users.setdefault(user_id, {"menu": ["main"]})
    return user_state.setdefault("board", {"state": "menu", "page": 0})


def _reset_state(state):
    state.clear()
    state.update({"state": "menu", "page": 0})


def _fmt_date(timestamp):
    return time.strftime("%b %d", time.localtime(timestamp))


def _short_body(body, width=36):
    one_line = " ".join(body.split())
    if len(one_line) <= width:
        return one_line
    return one_line[: width - 3].rstrip() + "..."


def _category_from_choice(command_clean):
    if command_clean.isdigit():
        index = int(command_clean) - 1
        if 0 <= index < len(CATEGORIES):
            return CATEGORIES[index]

    command_lower = command_clean.lower()
    for category, label in CATEGORIES:
        if command_lower in (category, label.lower()):
            return category, label
    return None


def _render_category(state, bbs_system):
    if state["category"] == "events":
        return _render_events(bbs_system)

    category = state["category"]
    label = state["label"]
    page = state.get("page", 0)
    offset = page * PAGE_SIZE
    posts = bbs_system.db.board_posts(category, PAGE_SIZE + 1, offset)

    lines = [label]
    if not posts:
        lines.append("No posts yet.")
    for index, post in enumerate(posts[:PAGE_SIZE], start=1):
        author = bbs_system.db.display_name_for(post["author_id"])
        lines.append(f"{index}. {author} - {_fmt_date(post['created_at'])} - {_short_body(post['body'])}")
    if len(posts) > PAGE_SIZE:
        lines.append("Next")
    lines.append("POST to add. Number to read. BACK.")
    return "\n".join(lines)


def _render_post(post, bbs_system):
    author = bbs_system.db.display_name_for(post["author_id"])
    return (
        f"From: {author}\n"
        f"Date: {_fmt_date(post['created_at'])}\n\n"
        f"{post['body']}\n\n"
        "3. Back"
    )


def _render_events(bbs_system):
    event = bbs_system.db.active_checkin_event()
    if not event:
        return (
            "Events Check-In\n"
            "No active check-in.\n"
            "1. Start Check-In\n"
            "2. Event Posts\n"
            "cd .. - Back"
        )
    return _render_checkin_list(event, bbs_system)


def _render_checkin_list(event, bbs_system):
    contacts = bbs_system.db.list_mail_contacts()
    entries = bbs_system.db.checkin_entries(event["id"])
    checked_ids = {entry["node_id"] for entry in entries}
    checked_names = [bbs_system.db.display_name_for(entry["node_id"]) for entry in entries]
    missing_names = [
        contact["display_name"]
        for contact in contacts
        if contact["node_id"] not in checked_ids
    ]
    ends = time.strftime("%b %d %H:%M", time.localtime(event["ends_at"]))

    lines = [event["title"], f"Ends {ends}"]
    lines.append("In: " + (", ".join(checked_names) if checked_names else "None"))
    lines.append("Out: " + (", ".join(missing_names) if missing_names else "None"))
    lines.append("1. Check In")
    lines.append("2. Refresh")
    lines.append("3. Event Posts")
    lines.append("cd .. - Back")
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    state = _board_state(bbs_system, user_id)
    command_clean = command.strip()
    command_lower = command_clean.lower()

    if command_lower in ("menu", "back"):
        _reset_state(state)
        return display_menu()

    if state["state"] == "await_post":
        if not command_clean:
            return "Post cannot be empty. Send the post text."
        bbs_system.db.create_board_post(state["category"], user_id, command_clean)
        state["page"] = 0
        if state["category"] == "events":
            state["state"] = "event_posts"
            return "Posted.\n\n" + _render_board_posts(state, bbs_system)
        state["state"] = "category"
        return "Posted.\n\n" + _render_category(state, bbs_system)

    if state["state"] == "post":
        if command_lower in ("3", "back"):
            state["state"] = "category"
            return _render_category(state, bbs_system)
        post = bbs_system.db.get_board_post(state["post_id"])
        return _render_post(post, bbs_system) if post else _render_category(state, bbs_system)

    if state["state"] == "category":
        if state["category"] == "events":
            event = bbs_system.db.active_checkin_event()
            if command_lower in ("1", "start", "start check-in", "start checkin"):
                if not event:
                    event_id = bbs_system.db.create_checkin_event(user_id)
                    bbs_system.db.check_in(event_id, user_id)
                    event = bbs_system.db.active_checkin_event()
                    return "Check-in started for 24 hours.\n\n" + _render_checkin_list(event, bbs_system)
                bbs_system.db.check_in(event["id"], user_id)
                return "Checked in.\n\n" + _render_checkin_list(event, bbs_system)
            if command_lower in ("2", "refresh", "list"):
                return _render_events(bbs_system)
            if command_lower in ("3", "posts", "event posts"):
                state["state"] = "event_posts"
                state["page"] = 0
                return _render_board_posts(state, bbs_system)
            return _render_events(bbs_system)

        if command_lower == "post":
            state["state"] = "await_post"
            return f"New post in {state['label']}.\nSend the post text."
        if command_lower == "next":
            state["page"] = state.get("page", 0) + 1
            return _render_category(state, bbs_system)
        if command_clean.isdigit():
            posts = bbs_system.db.board_posts(state["category"], PAGE_SIZE, state.get("page", 0) * PAGE_SIZE)
            index = int(command_clean) - 1
            if 0 <= index < len(posts):
                state["state"] = "post"
                state["post_id"] = posts[index]["id"]
                return _render_post(posts[index], bbs_system)
        return _render_category(state, bbs_system)

    if state["state"] == "event_posts":
        if command_lower == "post":
            state["state"] = "await_post"
            return f"New post in {state['label']}.\nSend the post text."
        if command_lower == "next":
            state["page"] = state.get("page", 0) + 1
            return _render_board_posts(state, bbs_system)
        if command_lower in ("checkin", "check-in", "back"):
            state["state"] = "category"
            return _render_events(bbs_system)
        if command_clean.isdigit():
            posts = bbs_system.db.board_posts(state["category"], PAGE_SIZE, state.get("page", 0) * PAGE_SIZE)
            index = int(command_clean) - 1
            if 0 <= index < len(posts):
                state["state"] = "post"
                state["post_id"] = posts[index]["id"]
                return _render_post(posts[index], bbs_system)
        return _render_board_posts(state, bbs_system)

    category = _category_from_choice(command_clean)
    if category:
        state.update({
            "state": "category",
            "category": category[0],
            "label": category[1],
            "page": 0,
        })
        return _render_category(state, bbs_system)

    return display_menu()


def _render_board_posts(state, bbs_system):
    category = state["category"]
    label = state["label"]
    page = state.get("page", 0)
    offset = page * PAGE_SIZE
    posts = bbs_system.db.board_posts(category, PAGE_SIZE + 1, offset)

    lines = [f"{label} Posts"]
    if not posts:
        lines.append("No posts yet.")
    for index, post in enumerate(posts[:PAGE_SIZE], start=1):
        author = bbs_system.db.display_name_for(post["author_id"])
        lines.append(f"{index}. {author} - {_fmt_date(post['created_at'])} - {_short_body(post['body'])}")
    if len(posts) > PAGE_SIZE:
        lines.append("Next")
    lines.append("POST to add. CHECKIN to return.")
    return "\n".join(lines)
