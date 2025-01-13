menu_name = "Escape Room"  # Required for module loading

def display_menu():
    return "Welcome to the Escape Room!\n" \
           "You are locked in a room. Explore, solve puzzles, and escape!\n" \
           "Use commands like 'north', 'examine', 'pick up', and 'use'.\n" \
           "'cd ..' to return to the main menu."

def init_game():
    """Initialize the game state."""
    return {
        "current_room": "start",  # Start room
        "inventory": [],  # Items collected by the player
        "rooms": {
            "start": {
                "description": "You are in a locked room. There is a door to the north and a table in the corner.",
                "objects": {"table": "An old wooden table with a drawer."},
                "items": {"key": "A rusty key inside the drawer."},
                "exits": {"north": "locked_door"}
            },
            "locked_door": {
                "description": "A locked door blocks your way. You see a keyhole.",
                "objects": {"door": "The door is locked. There’s a keyhole."},
                "items": {},
                "exits": {}
            }
        },
        "door_unlocked": False  # Track if the door is unlocked
    }

def process_command(user_id, command, bbs_system):
    """Handle commands for the Escape Room game."""
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]

    # Initialize the game if not already done
    if "escape_room" not in user_state:
        user_state["escape_room"] = init_game()

    game = user_state["escape_room"]

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    # Parse commands
    parts = command.strip().split(" ", 1)
    action = parts[0].lower()
    target = parts[1].lower() if len(parts) > 1 else None

    current_room = game["current_room"]
    room_data = game["rooms"][current_room]

    if action in ["north", "south", "east", "west"]:
        return move_player(action, game)
    elif action == "examine" and target:
        return examine_object(target, room_data)
    elif action == "pick" and target and target.startswith("up"):
        item = target[3:].strip()
        return pick_up_item(item, room_data, game)
    elif action == "use" and target:
        return use_item(target, game)
    elif action == "inventory":
        return f"Inventory: {', '.join(game['inventory']) if game['inventory'] else 'Empty'}"
    elif action == "help":
        return "Commands: north, south, east, west, examine [object], pick up [item], use [item on target], inventory, help."
    else:
        return "Invalid command. Type 'help' for a list of commands."

def move_player(direction, game):
    """Handle player movement."""
    current_room = game["current_room"]
    exits = game["rooms"][current_room].get("exits", {})
    if direction in exits:
        if exits[direction] == "locked_door" and not game["door_unlocked"]:
            return "The door is locked. You need to unlock it first."
        game["current_room"] = exits[direction]
        return f"You moved {direction}.\n\n{game['rooms'][game['current_room']]['description']}"
    else:
        return "You can't go that way."

def examine_object(target, room_data):
    """Handle examining objects."""
    if target in room_data.get("objects", {}):
        return room_data["objects"][target]
    else:
        return "You don't see that here."

def pick_up_item(item, room_data, game):
    """Handle picking up items."""
    items = room_data.get("items", {})
    if item in items:
        game["inventory"].append(item)
        del items[item]
        return f"You picked up {item}."
    else:
        return "You can't pick that up."

def use_item(target, game):
    """Handle using items."""
    if "key on door" in target and "key" in game["inventory"]:
        game["door_unlocked"] = True
        return "You used the key to unlock the door! You can now go north."
    else:
        return "You can't use that here."
