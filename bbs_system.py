import os
import importlib
from interface import Interface


class BBSSystem:
    def __init__(self):
        self.users = {}  # Store user states keyed by their IDs
        self.menu_modules = self.load_menu_modules()  # Load menu modules
        self.interface = Interface()  # Initialize the Meshtastic interface
        self.interface.handle_message = self.handle_message  # Link message handling

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

        for file in os.listdir(modules_folder):
            if file.endswith(".py") and not file.startswith("__"):
                module_name = file[:-3]  # Remove .py extension
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
        print(f"Loaded modules: {list(menu_modules.keys())}")
        return menu_modules

    def handle_message(self, user_id, message):
        """
        Process messages received from the interface.
        """
        if user_id not in self.users:
            response = self.start_session(user_id)
        else:
            response = self.process_command(user_id, message)
        return response

    def start_session(self, user_id):
        """
        Start a new BBS session for the user.
        """
        self.users[user_id] = {"menu": ["main"]}  # Menu stack to track navigation
        return self.display_menu(user_id)

    def process_command(self, user_id, command):
        """
        Process commands based on the user's current menu.
        """
        current_menu = self.users[user_id]["menu"][-1]  # Get the current menu from the stack

        # Handle global navigation commands
        if command.strip().lower() == "top":  # Go back to the main menu
            self.users[user_id]["menu"] = ["main"]
            return self.display_menu(user_id)
        elif command.strip().lower() == "cd ..":  # Go back one menu level
            if len(self.users[user_id]["menu"]) > 1:
                self.users[user_id]["menu"].pop()  # Remove the last menu
                return self.display_menu(user_id)
            else:
                return "You are already at the main menu."

        # Handle menu-specific commands
        if current_menu == "main":
            # Explicitly route to handle_main_menu for main menu commands
            return self.handle_main_menu(user_id, command)
        elif current_menu in self.menu_modules:
            # Route to the appropriate module
            module = self.menu_modules[current_menu]
            return module.process_command(user_id, command, self)
        else:
            return "Invalid command."

    def display_menu(self, user_id):
        """
        Display the current menu to the user.
        """
        current_menu = self.users[user_id]["menu"][-1]  # Get the current menu from the stack

        if current_menu == "main":
            menu_text = "Main Menu:\n"
            for index, menu_name in enumerate(self.menu_modules.keys(), start=1):
                menu_text += f"{index}. {menu_name}\n"
            menu_text += "Choose an option (e.g., '1').\n"
            menu_text += "'top' to go to Main Menu, 'cd ..' to go back one menu."
            return menu_text
        elif current_menu in self.menu_modules:
            module = self.menu_modules[current_menu]
            if hasattr(module, "display_menu"):
                return module.display_menu()
            else:
                return "This menu does not have a display_menu function."
        else:
            return "Invalid menu."

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
                module = self.menu_modules[selected_menu]
                return module.display_menu()
            else:
                return "Invalid option."
        except ValueError:
            return "Invalid input. Please enter a number."

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
