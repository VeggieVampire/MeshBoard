import time
from location_service import distance_between_locations

menu_name = "Hot Cold"  # Required for module loading

#The goal of "Hot Cold" is to locate a hidden target location on the map using distance-based feedback such as "warmer," "colder," or "HOT!" The first player to get within 10 feet (~3 meters) of the target wins the game.

def display_menu():
    return "Welcome to Hot Cold!\n" \
           "Set the game duration (in seconds) and find the hidden location!\n" \
           "Use commands:\n" \
           "1. Start 30 seconds\n" \
           "2. Start 60 seconds\n" \
           "'cd ..' to return to the main menu."

def haversine(lat1, lon1, lat2, lon2):
    """Compatibility wrapper for older tests/imports."""
    return distance_between_locations(lat1, lon1, lat2, lon2)

def process_command(user_id, command, bbs_system):
    """Handle commands for the Hot Cold game."""
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]
    
    # Initialize or reset the game state
    if "hot_cold" not in user_state:
        user_state["hot_cold"] = {
            "target_location": (35.652832, -97.478095),  # Example target (lat, lon)
            "durations": {"1": 30, "2": 60},
            "last_distance": None,
            "timer": None
        }

    game = user_state["hot_cold"]

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    if command in game["durations"]:
        duration = game["durations"][command]
        game["timer"] = time.time() + duration  # Set the timer
        return f"Hot Cold game started! You have {duration} seconds per round.\nSend any message for distance feedback."

    if not game["timer"]:
        return "No game in progress. Start a game first!"

    # Check remaining time
    remaining_time = game["timer"] - time.time()
    if remaining_time <= 0:
        return handle_game_update(user_id, bbs_system)

    return handle_game_update(user_id, bbs_system, reset_timer=False)

def handle_game_update(user_id, bbs_system, reset_timer=True):
    """Process the game update at the end of each round."""
    user_state = bbs_system.users[user_id]
    game = user_state["hot_cold"]

    location, message = bbs_system.get_recent_location_or_message(user_id)
    if message:
        return message

    target_lat, target_lon = game["target_location"]
    distance = distance_between_locations(
        target_lat,
        target_lon,
        location["latitude"],
        location["longitude"],
    )
    previous = game.get("last_distance")
    game["last_distance"] = distance

    if distance <= 3:
        game["timer"] = None
        return "HOT! You found the target!"

    if previous is None:
        feedback = f"You are {int(distance)} meters from the target."
    elif distance < previous:
        feedback = f"You are {int(distance)} meters from the target.\nWarmer!"
    elif distance > previous:
        feedback = f"Colder!\nYou are {int(distance)} meters away."
    else:
        feedback = f"Same distance.\nYou are {int(distance)} meters away."

    if reset_timer:
        game["timer"] = time.time() + game["durations"]["1"]  # Default to 30 seconds
    return feedback
