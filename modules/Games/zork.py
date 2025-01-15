menu_name = "ZORK"

def display_menu():
    return "Welcome to Zork!\n1. Start Game\n'cd ..' to return to the main menu."

def init_game():
    return {
        "location": "field",
        "inventory": []
    }

def process_command(user_id, command, bbs_system):
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]

    if "zork_game" not in user_state:
        if command == "1":
            user_state["zork_game"] = init_game()
            return handle_field(user_state["zork_game"])
        elif command.strip().lower() == "cd ..":
            bbs_system.users[user_id]["menu"].pop()
            return bbs_system.display_menu(user_id)
        else:
            return "Invalid choice. Enter '1' to start the game or 'cd ..' to exit."

    game = user_state["zork_game"]

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    if command.strip().lower() == "help":
        return "Available commands depend on your location. Try looking around or moving in a direction.\nExamples: 'look', 'go east', 'open mailbox'."

    if game["location"] == "field":
        return handle_field(game, command)
    elif game["location"] == "forest":
        return handle_forest(game, command)
    elif game["location"] == "clearing":
        return handle_clearing(game, command)
    elif game["location"] == "cave":
        return handle_cave(game, command)
    else:
        return "Unknown game state."

def handle_field(game, command=None):
    if command is None or command in ["look", "look around"]:
        return ("You are standing in an open field west of a white house, with a boarded front door.\n"
                "(A secret path leads southwest into the forest.)\n"
                "There is a Small Mailbox.\nWhat do you do?")
    elif command == "take mailbox":
        return "It is securely anchored."
    elif command in ["open mailbox", "look in mailbox"]:
        return "Opening the small mailbox reveals a leaflet."
    elif command == "go east":
        return "The door is boarded and you cannot remove the boards."
    elif command == "open door":
        return "The door cannot be opened."
    elif command == "take boards":
        return "The boards are securely fastened."
    elif command in ["look at house", "examine house"]:
        return "The house is a beautiful colonial house which is painted white. It is clear that the owners must have been extremely wealthy."
    elif command in ["go southwest", "go to secret path"]:
        game["location"] = "forest"
        return handle_forest(game)
    elif command == "read leaflet":
        return "Welcome to the Unofficial Python Version of Zork. Your mission is to find a Jade Statue."
    else:
        return "Invalid command. Try 'look', 'go southwest', or 'open mailbox'."

def handle_forest(game, command=None):
    if command is None or command in ["look", "look around"]:
        return "This is a forest, with trees in all directions. To the east, there appears to be sunlight.\nWhat do you do?"
    elif command == "go west":
        return "You would need a machete to go further west."
    elif command == "go north":
        return "The forest becomes impenetrable to the North."
    elif command == "go south":
        return "Storm-tossed trees block your way."
    elif command == "go east":
        game["location"] = "clearing"
        return handle_clearing(game)
    else:
        return "Invalid command. Try 'look' or 'go east'."

def handle_clearing(game, command=None):
    if command is None or command in ["look", "look around"]:
        return ("You are in a clearing, with a forest surrounding you on all sides. A path leads south.\n"
                "There is an open grating, descending into darkness.\nWhat do you do?")
    elif command == "go south":
        return "You see a large ogre and turn around."
    elif command in ["descend grating", "go down"]:
        game["location"] = "cave"
        return handle_cave(game)
    else:
        return "Invalid command. Try 'look' or 'descend grating'."

def handle_cave(game, command=None):
    if command is None or command in ["look", "look around"]:
        return "You are in a tiny cave with a dark, forbidding staircase leading down.\nThere is a skeleton of a human male in one corner.\nWhat do you do?"
    elif command in ["descend staircase", "go down"]:
        return ("You have entered a mud-floored room.\n"
                "Lying half buried in the mud is an old trunk, bulging with jewels.\n"
                "You have found the Jade Statue and have completed your quest!")
    elif command == "take skeleton":
        return "Why would you do that? Are you some sort of sicko?"
    elif command == "smash skeleton":
        return "Sick person. Have some respect mate."
    elif command == "light up room":
        return "You would need a torch or lamp to do that."
    elif command == "break skeleton":
        return "I have two questions: Why and With What?"
    else:
        return "Invalid command. Try 'look' or 'descend staircase'."
