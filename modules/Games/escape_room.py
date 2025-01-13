menu_name = "Escape Room"  # Required for module loading

def display_menu():
    # Display the introduction and instructions for the Escape Room game
    return (
        "Welcome to the Escape Room!\n"
        "You are locked in a room. Explore, solve puzzles, and escape!\n"
        "Use commands like 'north', 'south', 'east', 'west', 'examine', 'pick up', and 'use'.\n"
        "'cd ..' to return to the main menu."
    )

def init_game():
    """Initialize the game state."""
    return {
        "current_room": "start",  # Start room
        "inventory": [],  # Items collected by the player
        "rooms": {
            "start": {
                "description": "You are in a locked room. There is a door to the north, a table in the corner, and a painting on the wall.",
                "objects": {
                    "table": "An old wooden table with a drawer.",
                    "painting": "A painting of a landscape; it seems slightly askew."
                },
                "items": {},
                "exits": {"north": "locked_door", "east": "hidden_room"}
            },
            "locked_door": {
                "description": "A locked door blocks your way. You see a keyhole.",
                "objects": {"door": "The door is locked. There’s a keyhole."},
                "items": {},
                "exits": {"south": "start"}
            },
            "hidden_room": {
                "description": "You have entered a hidden room. There is a chest in the center and a bookshelf against the wall.",
                "objects": {
                    "chest": "An old chest with a combination lock.",
                    "bookshelf": "A dusty bookshelf filled with various books."
                },
                "items": {},
                "exits": {"west": "start"}
            }
        },
        "door_unlocked": False,  # Track if the door is unlocked
        "chest_unlocked": False  # Track if the chest is unlocked
    }

def process_command(user_id, command, bbs_system):
    """Handle commands for the Escape Room game."""
    # Check if the user exists in the system, and initialize user state if not
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]

    # Initialize the game if not already done
    if "escape_room" not in user_state:
        user_state["escape_room"] = init_game()

    game = user_state["escape_room"]

    # Return to the main menu if the user types 'cd ..'
    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    # Normalize command input and parse the action and target
    parts = command.strip().lower().replace("go ", "").replace("move ", "").split(" ", 1)
    action = parts[0]
    target = parts[1] if len(parts) > 1 else None

    current_room = game["current_room"]
    room_data = game["rooms"][current_room]

    # Handle directional movement
    if action in ["north", "south", "east", "west"]:
        return move_player(action, game)

    # Handle examining the room or objects
    if action in ["look", "examine"] and (target == "room" or not target):
        description = room_data["description"]
        exits = ", ".join(room_data.get("exits", {}).keys()) or "none"
        return f"{description}\nExits: {exits}."

    # Handle examining specific objects
    if action == "examine" and target:
        return examine_object(target, room_data, game)

    # Handle picking up items
    if action == "pick" and target and target.startswith("up"):
        item = target[3:].strip()
        return pick_up_item(item, room_data, game)

    # Handle using items
    if action == "use" and target:
        return use_item(target, game)

    # Handle displaying the inventory
    if action == "inventory":
        return f"Inventory: {', '.join(game['inventory']) if game['inventory'] else 'Empty'}"

    # Display help or handle unrecognized commands
    if action == "help" or action not in ["north", "south", "east", "west", "examine", "pick", "use", "inventory"]:
        exits = ", ".join(room_data.get("exits", {}).keys()) or "none"
        objects = ", ".join(room_data.get("objects", {}).keys()) or "none"
        return (
            f"Invalid command. Try these:\n"
            f"- Movement: north, south, east, west\n"
            f"- Examine: room, {objects}\n"
            f"- Pick up items in the room\n"
            f"- Use items from your inventory\n"
            f"Exits available: {exits}."
        )

    # Fallback for any unrecognized commands
    return "Invalid command. Type 'help' for a list of commands."

def move_player(direction, game):
    """Handle player movement."""
    # Determine if the player can move in the given direction
    current_room = game["current_room"]
    exits = game["rooms"][current_room].get("exits", {})
    if direction in exits:
        # Check if the door is locked before moving
        if exits[direction] == "locked_door" and not game["door_unlocked"]:
            return "The door is locked. You need to unlock it first."
        game["current_room"] = exits[direction]
        return f"You moved {direction}.\n\n{game['rooms'][game['current_room']]['description']}"
    else:
        return "You can't go that way."

def examine_object(target, room_data, game):
    """Handle examining objects."""
    # Check if the target object is in the current room
    if target in room_data.get("objects", {}):
        if target == "table":
            return "An old wooden table with a drawer. Maybe you should open the drawer."
        elif target == "drawer":
            if "key" not in game["inventory"]:
                room_data["items"]["key"] = "A rusty key inside the drawer."
                return "You opened the drawer and found a rusty key."
            else:
                return "The drawer is empty."
        elif target == "painting":
            return "A painting of a landscape; it seems slightly askew. Perhaps you should adjust it."
        elif target == "chest":
            if not game["chest_unlocked"]:
                return "An old chest with a combination lock. Maybe there's a clue nearby."
            else:
                return "The chest is open. Inside, you see a shiny gem."
        elif target == "bookshelf":
            return "A dusty bookshelf filled with various books. One book seems out of place."
        else:
            return room_data["objects"][target]
    else:
        return "You don't see that here."

def pick_up_item(item, room_data, game):
    """Handle picking up items."""
    # Check if the item is available in the room
    items = room_data.get("items", {})
    if item in items:
        game["inventory"].append(item)
        del items[item]
        return f"You picked up {item}."
    else:
        return "You can't pick that up."

def use_item(target, game):
    """Handle using items."""
    # Check if the user can use the item in the current context
    if "key" in target and "key" in game["inventory"] and game["current_room"] == "locked_door":
        game["door_unlocked"] = True
        return "You used the key to unlock the door! You can now go north."
    else:
        return "You can't use that here."
