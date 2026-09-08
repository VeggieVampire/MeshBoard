import time


menu_name = "Mail"
PAGE_SIZE = 8


def display_menu():
    return (
        "Mail\n"
        "1. Inbox\n"
        "2. Send\n"
        "3. Add AddressBook\n"
        "4. Archive\n"
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
    return user_state.setdefault("mail", {"state": "menu", "page": 0})


def _reset_state(state):
    state.clear()
    state.update({"state": "menu", "page": 0})


def _render_inbox(user_id, bbs_system):
    messages = bbs_system.db.inbox(user_id)
    unread = sum(1 for msg in messages if msg["read_at"] is None)
    if not messages:
        return "Inbox - no messages.\ncd .. - Back"

    lines = [f"Inbox - {unread} unread"]
    for index, msg in enumerate(messages[:PAGE_SIZE], start=1):
        sender = bbs_system.db.display_name_for(msg["sender_id"])
        flag = "*" if msg["read_at"] is None else " "
        lines.append(f"{index}. {flag} {sender} - {_fmt_date(msg['created_at'])} - {_short_body(msg['body'])}")
    if len(messages) > PAGE_SIZE:
        lines.append(f"Showing 1-{PAGE_SIZE} of {len(messages)}.")
    lines.append("Reply with a number to read. cd .. - Back")
    return "\n".join(lines)


def _render_message(msg, bbs_system):
    sender = bbs_system.db.display_name_for(msg["sender_id"])
    return (
        f"From: {sender}\n"
        f"Date: {_fmt_date(msg['created_at'], True)}\n"
        f"ID: {msg['id']}\n\n"
        f"{msg['body']}\n\n"
        "Reply REPLY to answer, ARCHIVE to archive, or BACK for Inbox."
    )


def _render_contacts(state, bbs_system):
    contacts = bbs_system.db.list_mail_contacts()
    page = state.get("page", 0)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(contacts))

    if not contacts:
        return "AddressBook is empty.\nAsk people to use Add AddressBook."

    lines = [f"Send - AddressBook {start + 1}-{end} of {len(contacts)}"]
    for index, row in enumerate(contacts[start:end], start=1):
        lines.append(f"{index}. {row['display_name']}")
    if end < len(contacts):
        lines.append("9. Next")
    lines.append("Choose a number, or enter a !nodeid.")
    return "\n".join(lines)


def _contact_from_choice(command_clean, state, bbs_system):
    if command_clean.startswith("!"):
        bbs_system.db.upsert_user(command_clean)
        return command_clean

    if not command_clean.isdigit():
        return None

    selected = int(command_clean)
    if selected == 9:
        return "NEXT"
    if not 1 <= selected <= PAGE_SIZE:
        return None

    contacts = bbs_system.db.list_mail_contacts()
    index = state.get("page", 0) * PAGE_SIZE + selected - 1
    if 0 <= index < len(contacts):
        return contacts[index]["node_id"]
    return None


def _render_archive(user_id, bbs_system):
    messages = bbs_system.db.archived_inbox(user_id)
    if not messages:
        return "Archive - no archived messages.\ncd .. - Back"

    lines = ["Archive"]
    for index, msg in enumerate(messages[:PAGE_SIZE], start=1):
        sender = bbs_system.db.display_name_for(msg["sender_id"])
        lines.append(f"{index}. {sender} - {_fmt_date(msg['created_at'])} - {_short_body(msg['body'])}")
    if len(messages) > PAGE_SIZE:
        lines.append(f"Showing 1-{PAGE_SIZE} of {len(messages)}.")
    lines.append("Reply with a number to view. DELETE <number> removes it.")
    return "\n".join(lines)


def process_command(user_id, command, bbs_system):
    state = _mail_state(bbs_system, user_id)
    command_clean = command.strip()
    command_lower = command_clean.lower()

    if command_lower in ("menu", "back"):
        _reset_state(state)
        return display_menu()

    if command_lower == "archive" and state["state"] != "message":
        state["state"] = "archive"
        return _render_archive(user_id, bbs_system)

    if state["state"] == "await_addressbook":
        if command_lower in ("yes", "y"):
            state["state"] = "await_addressbook_name"
            return "What simple ID/name should show in AddressBook?"
        _reset_state(state)
        return "Not added to AddressBook."

    if state["state"] == "await_addressbook_name":
        if not command_clean:
            return "Enter a simple ID/name for AddressBook."
        simple_id = command_clean[:40]
        bbs_system.db.set_mail_listed(user_id, simple_id, True)
        _reset_state(state)
        return f"Added to AddressBook as {simple_id}."

    if state["state"] == "send_select":
        recipient = _contact_from_choice(command_clean, state, bbs_system)
        if recipient == "NEXT":
            contacts = bbs_system.db.list_mail_contacts()
            if (state.get("page", 0) + 1) * PAGE_SIZE >= len(contacts):
                return "No more AddressBook entries."
            state["page"] = state.get("page", 0) + 1
            return _render_contacts(state, bbs_system)
        if not recipient:
            return _render_contacts(state, bbs_system)
        state["recipient_id"] = recipient
        state["state"] = "await_body"
        return f"To: {bbs_system.db.display_name_for(recipient)}\nEnter the message body:"

    if state["state"] == "await_body":
        if not command_clean:
            return "Message body cannot be empty. Enter the message body:"
        bbs_system.db.send_message(user_id, state["recipient_id"], command_clean)
        recipient = bbs_system.db.display_name_for(state["recipient_id"])
        _reset_state(state)
        return f"Message saved for {recipient}."

    if state["state"] == "inbox":
        messages = bbs_system.db.inbox(user_id)
        try:
            index = int(command_clean) - 1
        except ValueError:
            return _render_inbox(user_id, bbs_system)
        if 0 <= index < min(len(messages), PAGE_SIZE):
            msg = messages[index]
            bbs_system.db.mark_read(msg["id"], user_id)
            state["state"] = "message"
            state["message_id"] = msg["id"]
            return _render_message(msg, bbs_system)
        return "Invalid message number."

    if state["state"] == "message":
        msg = bbs_system.db.get_message_for_user(state["message_id"], user_id)
        if not msg or msg["recipient_id"] != user_id:
            state["state"] = "inbox"
            return _render_inbox(user_id, bbs_system)
        if command_lower == "reply":
            state["recipient_id"] = msg["sender_id"]
            state["state"] = "await_body"
            return f"Reply to {bbs_system.db.display_name_for(msg['sender_id'])}:\nEnter the message body:"
        if command_lower == "archive":
            bbs_system.db.soft_delete_message(msg["id"], user_id)
            state["state"] = "inbox"
            return "Message archived.\n\n" + _render_inbox(user_id, bbs_system)
        return _render_message(msg, bbs_system)

    if state["state"] == "archive":
        messages = bbs_system.db.archived_inbox(user_id)
        delete = command_lower.startswith("delete ")
        value = command_clean.split(maxsplit=1)[1] if delete and " " in command_clean else command_clean
        try:
            index = int(value) - 1
        except ValueError:
            return _render_archive(user_id, bbs_system)
        if 0 <= index < min(len(messages), PAGE_SIZE):
            msg = messages[index]
            if delete:
                bbs_system.db.delete_archived_message(msg["id"], user_id)
                return "Archived message deleted.\n\n" + _render_archive(user_id, bbs_system)
            return _render_message(msg, bbs_system)
        return "Invalid archive number."

    if state["state"] == "menu":
        if command_lower in ("1", "inbox"):
            state["state"] = "inbox"
            return _render_inbox(user_id, bbs_system)
        if command_lower in ("2", "send"):
            state["state"] = "send_select"
            state["page"] = 0
            return _render_contacts(state, bbs_system)
        if command_lower in ("3", "add addressbook", "add address book"):
            state["state"] = "await_addressbook"
            return "Add you to AddressBook so others can send you mail? Reply YES or NO."
        if command_lower in ("4", "archive"):
            state["state"] = "archive"
            return _render_archive(user_id, bbs_system)
        return "Invalid choice. Choose Inbox, Send, Add AddressBook, Archive, or cd .. to return."

    _reset_state(state)
    return display_menu()
