import os
import json

menu_name = "Address List"  # Required for module loading

# Path to the JSON file, stored in the same directory as this script
FILE_PATH = os.path.dirname(os.path.abspath(__file__))
ADDRESS_LIST_FILE = os.path.join(FILE_PATH, "address_list.json")

def load_address_list():
    """Load the address list from storage."""
    if os.path.exists(ADDRESS_LIST_FILE):
        with open(ADDRESS_LIST_FILE, "r") as file:
            return json.load(file)
    return {}

def save_address_list(address_list):
    """Save the address list to storage."""
    with open(ADDRESS_LIST_FILE, "w") as file:
        json.dump(address_list, file)

def display_menu():
    """Display the Address List menu."""
    return "Address List Module:\n" \
           "1. View Address List\n" \
           "2. Add Yourself to Address List\n" \
           "3. Remove Yourself from Address List\n" \
           "4. Toggle Online Status\n" \
           "'cd ..' to return to the main menu."

def process_command(user_id, command, bbs_system):
    """Handle commands for the Address List Module."""
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]

    # Initialize address list state
    if "address_list" not in user_state:
        user_state["address_list"] = {"state": "menu", "online": True}

    state = user_state["address_list"]["state"]

    # Load the address list from storage
    address_list = load_address_list()

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    if state == "menu":
        if command == "1":
            # View Address List
            if not address_list:
                return "The address list is empty."
            contact_list = "\n".join([f"{user} (Online)" if details.get("online", False) else f"{user}"
                                      for user, details in address_list.items()])
            return f"Address List:\n{contact_list}\n\nType 'cd ..' to return to the menu."
        elif command == "2":
            # Add Yourself
            if user_id in address_list:
                return "You are already in the address list."
            address_list[user_id] = {"online": user_state["address_list"]["online"]}
            save_address_list(address_list)
            return "You have been added to the address list."
        elif command == "3":
            # Remove Yourself
            if user_id not in address_list:
                return "You are not in the address list."
            del address_list[user_id]
            save_address_list(address_list)
            return "You have been removed from the address list."
        elif command == "4":
            # Toggle Online Status
            user_state["address_list"]["online"] = not user_state["address_list"]["online"]
            if user_id in address_list:
                address_list[user_id]["online"] = user_state["address_list"]["online"]
            save_address_list(address_list)
            status = "Online" if user_state["address_list"]["online"] else "Offline"
            return f"Your online status is now: {status}."
        else:
            return "Invalid choice. Please choose 1, 2, 3, or 4, or type 'cd ..' to return."

    return "Unexpected error. Returning to menu."
