import time
import math

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
    """Calculate the distance in meters between two latitude/longitude points."""
    R = 6371e3  # Radius of the Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

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
            "player_distances": {},
            "timer": None
        }

    game = user_state["hot_cold"]

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    if command in game["durations"]:
        duration = game["durations"][command]
        game["timer"] = time.time() + duration  # Set the timer
        return f"Hot Cold game started! You have {duration} seconds per round."

    if not game["timer"]:
        return "No game in progress. Start a game first!"

    # Check remaining time
    remaining_time = game["timer"] - time.time()
    if remaining_time <= 0:
        return handle_game_update(user_id, bbs_system)

    return f"Time remaining: {int(remaining_time)} seconds."

def handle_game_update(user_id, bbs_system):
    """Process the game update at the end of each round."""
    user_state = bbs_system.users[user_id]
    game = user_state["hot_cold"]

    # Example positions: these should come from the interface
    player_positions = {
        "!user1": (35.652000, -97.478000),  # Example lat/lon
        "!user2": (35.651500, -97.477500),
    }

    target_lat, target_lon = game["target_location"]

    # Calculate distances and determine "warmer" or "colder"
    messages = []
    for player_id, (player_lat, player_lon) in player_positions.items():
        distance = haversine(target_lat, target_lon, player_lat, player_lon)
        prev_distance = game["player_distances"].get(player_id, float("inf"))

        if player_id not in game["player_distances"]:
            messages.append(f"Player {player_id}: {int(distance)} meters from the target.")
        else:
            if distance < prev_distance:
                messages.append(f"Player {player_id}: Warmer! {int(distance)} meters away.")
            else:
                messages.append(f"Player {player_id}: Colder! {int(distance)} meters away.")

        game["player_distances"][player_id] = distance

        # Check if a player is within 10 feet (3 meters)
        if distance <= 3:
            return f"HOT! Player {player_id} found the target!"

    # Reset the timer for the next round
    game["timer"] = time.time() + game["durations"]["1"]  # Default to 30 seconds

    return "\n".join(messages)
