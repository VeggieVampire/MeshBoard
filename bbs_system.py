import os
import importlib
import time
import logging
from config import load_config
from database import Database
from interface import Interface
from local_ai_service import LocalAIManager
from location_service import location_age, stale_location_message


MAIN_MENU_ORDER = ("Location", "Games", "Mail", "Who's Been Here", "Message Board", "Check-Ins", "Local AI")
GAMES_MENU_ORDER = ("Hot Cold", "ZORK", "Tic Tac Toe", "Escape Room")


def normalize_command(command):
    command_clean = command.strip()
    command_lower = command_clean.lower()
    if command_lower in ("top", "menu", "main menu"):
        return "top"
    if command_lower in ("cd ..", "cd.."):
        return "cd .."
    return command_lower


def order_menu_items(menu_items, preferred_order=()):
    ordered = {}
    for name in preferred_order:
        if name in menu_items:
            ordered[name] = menu_items[name]
    for name in sorted(menu_items):
        if name not in ordered:
            ordered[name] = menu_items[name]
    return ordered


def is_number_choice(command):
    try:
        int(command.strip())
        return True
    except ValueError:
        return False


def game_module_key(module):
    module_name = getattr(module, "__name__", "")
    return module_name.rsplit(".", 1)[-1]


class BBSSystem:
    def __init__(self, config=None, database=None, interface=None):
        self.config = config or load_config()
        self.db = database or Database(self.config["database"]["path"])
        self.users = {}  # Store user states keyed by their IDs
        self.node_locations = {}
        self.local_ai_manager = LocalAIManager(self.config.get("local_ai", {}))
        self.menu_modules = self.load_menu_modules()  # Load menu modules
        self.interface = interface or Interface(self.config)  # Initialize the Meshtastic interface
        self.interface.handle_message = self.handle_message  # Link message handling
        self.interface.handle_position = self.update_node_location
        self.logger = logging.getLogger(__name__)

    def load_menu_modules(self):
        """
        Dynamically load all menu modules from the 'modules' folder.
        """
        menu_modules = {}
        current_dir = os.path.dirname(os.path.abspath(__file__))
        modules_folder = os.path.join(current_dir, "modules")

        print(f"Looking for modules in: {modules_folder}")

        if not os.path.exists(modules_folder):
            print("Modules folder does not exist!")
            return menu_modules

        for item in os.listdir(modules_folder):
            item_path = os.path.join(modules_folder, item)
            if os.path.isfile(item_path) and item.endswith(".py") and not item.startswith("__"):
                module_name = item[:-3]  # Remove .py extension
                try:
                    module = importlib.import_module(f"modules.{module_name}")
                    if hasattr(module, "menu_name") and hasattr(module, "process_command"):
                        menu_name = module.menu_name.strip()
                        if menu_name:  # Ensure menu_name is valid
                            print(f"Loaded module: {menu_name}")
                            menu_modules[menu_name] = module
                        else:
                            print(f"Skipping {module_name}: Empty menu_name")
                    else:
                        print(f"Skipping {module_name}: Missing required attributes")
                except Exception as e:
                    print(f"Error loading module '{module_name}': {e}")
            elif os.path.isdir(item_path):  # Handle folders as package modules or submenus
                package_module_name = f"modules.{item}"
                try:
                    package_module = importlib.import_module(package_module_name)
                    if hasattr(package_module, "menu_name") and hasattr(package_module, "process_command"):
                        menu_name = package_module.menu_name.strip()
                        if menu_name:
                            print(f"Loaded package module: {menu_name}")
                            menu_modules[menu_name] = package_module
                            continue
                except Exception:
                    pass

                submenu = {}
                for sub_file in os.listdir(item_path):
                    if sub_file.endswith(".py") and not sub_file.startswith("__"):
                        sub_module_name = sub_file[:-3]  # Remove .py extension
                        try:
                            sub_module = importlib.import_module(f"modules.{item}.{sub_module_name}")
                            if hasattr(sub_module, "menu_name") and hasattr(sub_module, "process_command"):
                                menu_name = sub_module.menu_name.strip()
                                if menu_name:
                                    print(f"Loaded submodule: {menu_name} under menu '{item}'")
                                    submenu[menu_name] = sub_module
                                else:
                                    print(f"Skipping {sub_module_name}: Empty menu_name")
                            else:
                                print(f"Skipping {sub_module_name}: Missing required attributes")
                        except Exception as e:
                            print(f"Error loading submodule '{sub_module_name}': {e}")
                if submenu:
                    menu_modules[item] = {"submodules": order_menu_items(submenu, GAMES_MENU_ORDER)}
        menu_modules = order_menu_items(menu_modules, MAIN_MENU_ORDER)
        print(f"Loaded modules: {list(menu_modules.keys())}")
        return menu_modules

    def handle_message(self, user_id, message):
        """
        Process messages received from the interface.
        """
        self.db.record_user_command(user_id)
        if user_id not in self.users:
            welcome = self.start_session(user_id)
            if message.strip():
                response = self.process_command(user_id, message)
                if response.startswith("Invalid"):
                    return self.first_contact_message(user_id)
                return response
            return welcome
        else:
            response = self.process_command(user_id, message)
        return response

    def start_session(self, user_id):
        """
        Start a new BBS session for the user.
        """
        self.users[user_id] = {"menu": ["main"]}  # Menu stack to track navigation
        return self.display_menu(user_id)

    def first_contact_message(self, user_id):
        return (
            "Hello. This is MeshBoard, a local text BBS over Meshtastic.\n"
            "Send a number to choose a menu item, or send top any time to restart.\n\n"
            f"{self.display_menu(user_id)}"
        )

    def update_node_location(self, user_id, position):
        latitude = position.get("latitude")
        longitude = position.get("longitude")
        if latitude is None or longitude is None:
            return
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            self.logger.warning("Ignoring malformed GPS location from %s", user_id)
            return

        timestamp = position.get("timestamp", position.get("time"))
        received_at = int(time.time())
        self.node_locations[user_id] = {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": position.get("altitude"),
            "timestamp": int(timestamp) if timestamp else received_at,
            "received_at": received_at,
        }

    def get_latest_location(self, user_id):
        return self.node_locations.get(user_id)

    def get_location_age(self, user_id):
        return location_age(self.get_latest_location(user_id))

    def get_recent_location_or_message(self, user_id):
        location = self.get_latest_location(user_id)
        if not location:
            return None, "No GPS position is available for your node yet.\nWait for your node to send a position update and try again."
        age = self.get_location_age(user_id)
        freshness = self.config["gps"]["freshness_seconds"]
        if age is not None and age > freshness:
            return None, stale_location_message(age)
        return location, None

    def ask_local_ai(self, prompt, system=None, model=None, timeout=None):
        self.local_ai_manager.update_config(self.config.get("local_ai", {}))
        ok, response = self.local_ai_manager.ask(prompt, system=system, model=model, timeout=timeout)
        return response

    def process_command(self, user_id, command):
        """
        Process commands based on the user's current menu.
        """
        command_clean = command.strip()
        command_lower = normalize_command(command_clean)
        current_menu = self.users[user_id]["menu"][-1]  # Get the current menu from the stack

        # Handle global navigation commands before module-specific handlers.
        if command_lower == "top":  # Go back to the main menu
            module = self.users[user_id].get("module_control")
            if hasattr(module, "exit_menu"):
                module.exit_menu(user_id, self)
            self.users[user_id]["menu"] = ["main"]
            self.users[user_id].pop("module_control", None)
            return self.display_menu(user_id)
        elif command_lower == "cd ..":  # Go back one menu level
            if self.users[user_id].pop("module_control", None):
                menu_data = self.menu_modules.get(current_menu)
                if hasattr(menu_data, "display_menu"):
                    return menu_data.display_menu()
                return self.display_menu(user_id)
            if len(self.users[user_id]["menu"]) > 1:
                self.users[user_id]["menu"].pop()  # Remove the last menu
                return self.display_menu(user_id)
            else:
                return "You are already at the main menu."

        # Check if a module has taken control
        if "module_control" in self.users[user_id]:
            module = self.users[user_id]["module_control"]
            return module.process_command(user_id, command, self)

        # Handle menu-specific commands
        if current_menu == "main":
            response = self.handle_main_menu(user_id, command)
            if response.startswith("Invalid") and not is_number_choice(command):
                return self.first_contact_message(user_id)
            return response
        elif current_menu in self.menu_modules:
            menu_data = self.menu_modules[current_menu]
            if isinstance(menu_data, dict) and "submodules" in menu_data:
                return self.handle_submenu(user_id, command, menu_data["submodules"])
            elif hasattr(menu_data, "process_command"):
                self.users[user_id]["module_control"] = menu_data
                return menu_data.process_command(user_id, command, self)
            else:
                return "Invalid command."
        else:
            return "Invalid command."

    def handle_main_menu(self, user_id, command):
        """
        Handle user input in the main menu.
        """
        try:
            command_index = int(command) - 1
            menu_names = list(self.menu_modules.keys())
            if 0 <= command_index < len(menu_names):
                selected_menu = menu_names[command_index]
                self.users[user_id]["menu"].append(selected_menu)  # Add to the menu stack
                if isinstance(self.menu_modules[selected_menu], dict) and "submodules" in self.menu_modules[selected_menu]:
                    return self.display_submenu(selected_menu)
                else:
                    module = self.menu_modules[selected_menu]
                    self.users[user_id]["module_control"] = module
                    if hasattr(module, "enter_menu"):
                        return module.enter_menu(user_id, self)
                    return module.display_menu() if hasattr(module, "display_menu") else "No menu available."
            else:
                return "Invalid option."
        except ValueError:
            return "Invalid input. Please enter a number."

    def handle_submenu(self, user_id, command, submodules):
        """
        Handle user input in a submenu.
        """
        try:
            command_index = int(command) - 1
            submenu_names = list(self.enabled_submodules(submodules).keys())
            if 0 <= command_index < len(submenu_names):
                selected_submodule = submodules[submenu_names[command_index]]
                self.users[user_id]["module_control"] = selected_submodule  # Assign control to the submodule
                if hasattr(selected_submodule, "enter_menu"):
                    return selected_submodule.enter_menu(user_id, self)
                return selected_submodule.display_menu() if hasattr(selected_submodule, "display_menu") else "No menu available."
            else:
                return "Invalid option."
        except ValueError:
            return "Invalid input. Please enter a number."

    def enabled_submodules(self, submodules):
        enabled = {}
        for name, module in submodules.items():
            if self.db.is_game_enabled(game_module_key(module)):
                enabled[name] = module
        return enabled

    def display_menu(self, user_id):
        """
        Display the current menu to the user.
        """
        current_menu = self.users[user_id]["menu"][-1]  # Get the current menu from the stack

        if current_menu == "main":
            menu_text = "Main Menu:\n"
            unread = self.db.unread_count(user_id)
            if unread:
                menu_text = f"Welcome back.\nYou have {unread} unread message{'s' if unread != 1 else ''}.\n\n" + menu_text
            for index, menu_name in enumerate(self.menu_modules.keys(), start=1):
                menu_text += f"{index}. {menu_name}\n"
            menu_text += "Reply number. top - Main, cd .. - Back"
            return menu_text
        elif (
            current_menu in self.menu_modules
            and isinstance(self.menu_modules[current_menu], dict)
            and "submodules" in self.menu_modules[current_menu]
        ):
            return self.display_submenu(current_menu)
        else:
            return "Invalid menu."

    def display_submenu(self, menu_name):
        """
        Display a submenu to the user.
        """
        submodules = self.menu_modules[menu_name]["submodules"]
        submodules = self.enabled_submodules(submodules)
        menu_text = f"{menu_name.capitalize()} Menu:\n"
        if not submodules:
            return f"{menu_name.capitalize()} Menu:\nNo games enabled.\n'cd ..' to go back."
        for index, sub_name in enumerate(submodules.keys(), start=1):
            menu_text += f"{index}. {sub_name}\n"
        menu_text += "Choose an option (e.g., '1').\n"
        menu_text += "'cd ..' to go back."
        return menu_text

    def run(self):
        """
        Start the interface and BBS system.
        """
        print("BBS System running...")
        self.interface.run()


# Standalone execution
if __name__ == "__main__":
    bbs = BBSSystem()
    bbs.run()
