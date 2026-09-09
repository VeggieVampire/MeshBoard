import threading


menu_name = "Local AI"

SYSTEM_PROMPT = (
    "You are MeshBoard Local AI. Reply in plain text for Meshtastic. "
    "Be concise, practical, and avoid markdown tables."
)


def display_menu():
    return (
        "Local AI\n"
        "Ask short questions. Replies may arrive in numbered parts.\n"
        "top or end of line - shut down AI and return to Main."
    )


def _ai_state(bbs_system, user_id):
    user_state = bbs_system.users.setdefault(user_id, {"menu": ["main"]})
    return user_state.setdefault("local_ai", {"state": "idle"})


def _send_later(bbs_system, user_id, text):
    interface = getattr(bbs_system, "interface", None)
    sender = getattr(interface, "send_message", None)
    if sender:
        sender(user_id, text)


def enter_menu(user_id, bbs_system):
    state = _ai_state(bbs_system, user_id)
    state["state"] = "booting"
    state["session"] = state.get("session", 0) + 1
    session = state["session"]
    stop_event = threading.Event()
    state["stop_event"] = stop_event

    def boot():
        if stop_event.is_set():
            return
        ok, message = bbs_system.local_ai_manager.ensure_started()
        if ok and not stop_event.is_set():
            ok, message = bbs_system.local_ai_manager.wait_until_ready(stop_event=stop_event)
        if stop_event.is_set() or state.get("session") != session:
            return
        state["state"] = "ready" if ok else "failed"
        if ok:
            _send_later(bbs_system, user_id, "Local AI is ready. Ask any short question.")
        else:
            _send_later(bbs_system, user_id, message)

    threading.Thread(target=boot, daemon=True).start()
    return "Local AI booting up...\n\n" + display_menu()


def exit_menu(user_id, bbs_system):
    state = _ai_state(bbs_system, user_id)
    state["state"] = "idle"
    state["session"] = state.get("session", 0) + 1
    stop_event = state.get("stop_event")
    if stop_event:
        stop_event.set()
    bbs_system.local_ai_manager.shutdown()


def process_command(user_id, command, bbs_system):
    command_clean = command.strip()
    command_lower = command_clean.lower()
    state = _ai_state(bbs_system, user_id)

    if command_lower in ("end of line", "eol", "quit", "exit"):
        exit_menu(user_id, bbs_system)
        bbs_system.users[user_id]["menu"] = ["main"]
        bbs_system.users[user_id].pop("module_control", None)
        return "Local AI shut down.\n\n" + bbs_system.display_menu(user_id)

    if command_lower in ("help", "menu", "?"):
        return display_menu()

    if state.get("state") == "booting":
        return "Local AI is still booting.\n\n" + display_menu()

    if not command_clean:
        return "Send a short question, or send end of line to shut down AI."

    state["state"] = "ready"
    ok, response = bbs_system.local_ai_manager.ask(command_clean, system=SYSTEM_PROMPT)
    if not ok:
        return response
    return response
