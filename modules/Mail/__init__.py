import time


menu_name = "Mail"


def display_menu():
    return (
        "Mail\n"
        "1. Inbox\n"
        "2. Send Message\n"
        "3. Sent Messages\n"
        "4. Address List\n"
        "5. Delete / Archive\n"
        "NAME <name> - Set display name\n"
        "cd .. - Back"
    )


def _fmt_date(timestamp, include_time=False):
    fmt = "%b %d, %Y %I:%M %p" if include_time else "%b %d"
    return time.strftime(fmt, time.localtime(timestamp))


def _short_body(body, width=32):
    one_line = " ".join(body.split())
    if len(one_line) <= width:
        return one_line
    return one_line[: width - 3].rstrip() + "..."


def _mail_state(bbs_system, user_id):
    user_state = bbs_system.users.setdefault(user_id, {"menu": ["main"]})
    return user_state.setdefault("mail", {"state": "menu"})


def _render_inbox(user_id, bbs_system):
    messages = bbs_system.db.inbox(user_id)
    unread = sum(1 for msg in messages if msg["read_at"] is None)
    if not messages:
        return "Inbox - no messages.\ncd .. - Back"
    lines = [f"Inbox - {unread} unread"]
    for index, msg in enumerate(messages[:8], start=1):
        sender = bbs_system.db.display_name_for(msg["sender_id"])
        flag = "*" if msg["read_at"] is None else " "
        lines.append(f"{index}. {flag} {sender} - {_fmt_date(msg['created_at'])}")
    if len(messages) > 8:
        lines.append(f"Showing 1-8 of {len(messages)}.")
    lines.append("Reply with a number to read. cd .. - Back")
    return "\n".join(lines)


def _render_sent(user_id, bbs_system):
    messages = bbs_system.db.sent(user_id)
    if not messages:
        return "No sent messages.\ncd .. - Back"
    lines = ["Sent Messages"]
    for index, msg in enumerate(messages[:8], start=1):
        recipient = bbs_system.db.display_name_for(msg["recipient_id"])
        lines.append(f"{index}. {recipient} - {_fmt_date(msg['created_at'])} - {_short_body(msg['body'])}")
    if len(messages) > 8:
        lines.append(f"Showing 1-8 of {len(messages)}.")
    lines.append("cd .. - Back")
    return "\n".join(lines)


def _render_address_list(bbs_system):
    users = bbs_system.db.list_users()
    if not users:
        return "The address list is empty."
    lines = ["Address List"]
    now = time.time()
    for index, user in enumerate(users[:10], start=1):
        name = user["display_name"] or user["node_id"]
        age_minutes = int(max(0, now - user["last_seen"]) // 60)
        seen = "just now" if age_minutes == 0 else f"{age_minutes} min ago"
        lines.append(f"{index}. {name} ({user['node_id']}) Last seen: {seen}")
    if len(users) > 10:
        lines.append(f"Showing 1-10 of {len(users)}.")
    return "\n".join(lines)


def _resolve_recipient(text, bbs_system):
    value = text.strip()
    if value.isdigit():
        users = bbs_system.db.list_users()
        index = int(value) - 1
        if 0 <= index < len(users):
            return users[index]["node_id"]
    if value.startswith("!"):
        return value
    matches = [
        row for row in bbs_system.db.list_users()
        if row["display_name"] and row["display_name"].lower() == value.lower()
    ]
    if len(matches) == 1:
        return matches[0]["node_id"]
    if len(matches) > 1:
        return None
    return None


def process_command(user_id, command, bbs_system):
    state = _mail_state(bbs_system, user_id)
    command_clean = command.strip()
    command_lower = command_clean.lower()

    if command_lower.startswith("name "):
        display_name = command_clean[5:].strip()
        if not display_name:
            return "Enter a display name after NAME."
        bbs_system.db.set_display_name(user_id, display_name[:40])
        return f"Display name saved as {display_name[:40]}."

    if command_lower in ("menu", "back"):
        state.clear()
        state["state"] = "menu"
        return display_menu()

    if state["state"] == "await_recipient":
        recipient = _resolve_recipient(command_clean, bbs_system)
        if not recipient:
            return "Recipient not found. Enter a Meshtastic node ID like !a1b2c3d4 or an exact unique display name."
        state["recipient_id"] = recipient
        state["state"] = "await_body"
        return "Enter the message body:"

    if state["state"] == "await_body":
        if not command_clean:
            return "Message body cannot be empty. Enter the message body:"
        bbs_system.db.upsert_user(state["recipient_id"])
        bbs_system.db.send_message(user_id, state["recipient_id"], command_clean)
        recipient = bbs_system.db.display_name_for(state["recipient_id"])
        state.clear()
        state["state"] = "menu"
        return f"Message saved for {recipient}."

    if state["state"] == "delete":
        try:
            message_id = int(command_clean)
        except ValueError:
            return "Enter a message ID to archive, or 'menu' to return."
        if bbs_system.db.soft_delete_message(message_id, user_id):
            state["state"] = "menu"
            return "Message archived."
        return "Message not found or not yours."

    if state["state"] == "inbox":
        messages = bbs_system.db.inbox(user_id)
        try:
            index = int(command_clean) - 1
        except ValueError:
            return _render_inbox(user_id, bbs_system)
        if 0 <= index < min(len(messages), 8):
            msg = messages[index]
            bbs_system.db.mark_read(msg["id"], user_id)
            sender = bbs_system.db.display_name_for(msg["sender_id"])
            return f"From: {sender}\nDate: {_fmt_date(msg['created_at'], True)}\nID: {msg['id']}\n\n{msg['body']}"
        return "Invalid message number."

    if state["state"] == "menu":
        if command_clean == "1":
            state["state"] = "inbox"
            return _render_inbox(user_id, bbs_system)
        if command_clean == "2":
            state["state"] = "await_recipient"
            return "Enter recipient number from Address List, node ID, or exact display name:"
        if command_clean == "3":
            return _render_sent(user_id, bbs_system)
        if command_clean == "4":
            return _render_address_list(bbs_system)
        if command_clean == "5":
            state["state"] = "delete"
            return "Enter the message ID to archive. You can only archive your own inbox/sent messages."
        return "Invalid choice. Choose 1-5, or cd .. to return."

    state.clear()
    state["state"] = "menu"
    return display_menu()
