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
            elif os.path.isdir(item_path):  # Handle folders as submenus
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
                    menu_modules[item] = {"submodules": submenu}
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

        # Check if a module has taken control
        if "module_control" in self.users[user_id]:
            module = self.users[user_id]["module_control"]
            if command.strip().lower() == "cd ..":  # Exit the module and return to the menu
                del self.users[user_id]["module_control"]
                return self.display_menu(user_id)
            else:
                # Forward command to the module
                return module.process_command(user_id, command, self)

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
            return self.handle_main_menu(user_id, command)
        elif current_menu in self.menu_modules:
            menu_data = self.menu_modules[current_menu]
            if "submodules" in menu_data:
                return self.handle_submenu(user_id, command, menu_data["submodules"])
            elif hasattr(menu_data, "process_command"):
                # Assign control to the module
                self.users[user_id]["module_control"] = menu_data
                return menu_data.display_menu() if hasattr(menu_data, "display_menu") else "Entering module..."
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
                if "submodules" in self.menu_modules[selected_menu]:
                    return self.display_submenu(selected_menu)
                else:
                    module = self.menu_modules[selected_menu]
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
            submenu_names = list(submodules.keys())
            if 0 <= command_index < len(submenu_names):
                selected_submodule = submodules[submenu_names[command_index]]
                self.users[user_id]["module_control"] = selected_submodule  # Assign control to the submodule
                return selected_submodule.display_menu() if hasattr(selected_submodule, "display_menu") else "No menu available."
            else:
                return "Invalid option."
        except ValueError:
            return "Invalid input. Please enter a number."

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
        elif current_menu in self.menu_modules and "submodules" in self.menu_modules[current_menu]:
            return self.display_submenu(current_menu)
        else:
            return "Invalid menu."

    def display_submenu(self, menu_name):
        """
        Display a submenu to the user.
        """
        submodules = self.menu_modules[menu_name]["submodules"]
        menu_text = f"{menu_name.capitalize()} Menu:\n"
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
