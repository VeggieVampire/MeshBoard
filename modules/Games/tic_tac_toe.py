import random

menu_name = "Tic Tac Toe"  # Required for module loading

def display_menu():
    return "Welcome to Tic Tac Toe!\n" \
           "1. Player vs Player\n" \
           "2. Player vs Computer\n" \
           "'cd ..' to return to the main menu."

def init_game(mode):
    """Initialize a new game state."""
    return {
        "board": [" "] * 9,  # 3x3 board as a list
        "current_player": "X",  # X always starts
        "winner": None,
        "turns": 0,
        "mode": mode  # "pvp" or "pvc"
    }

def render_board(board):
    """Render the game board as ASCII art with double underscores for empty cells."""
    formatted_board = [cell if cell != " " else "__" for cell in board]
    return f" {formatted_board[0]} | {formatted_board[1]} | {formatted_board[2]} \n" \
           "---+---+---\n" \
           f" {formatted_board[3]} | {formatted_board[4]} | {formatted_board[5]} \n" \
           "---+---+---\n" \
           f" {formatted_board[6]} | {formatted_board[7]} | {formatted_board[8]} "

def check_winner(board):
    """Check if there's a winner on the board."""
    winning_combinations = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),  # Rows
        (0, 3, 6), (1, 4, 7), (2, 5, 8),  # Columns
        (0, 4, 8), (2, 4, 6)  # Diagonals
    ]
    for combo in winning_combinations:
        if board[combo[0]] == board[combo[1]] == board[combo[2]] and board[combo[0]] != " ":
            return board[combo[0]]  # Return the winner ("X" or "O")
    return None

def computer_move(board):
    """Choose a move for the computer."""
    available_positions = [i for i, cell in enumerate(board) if cell == " "]
    return random.choice(available_positions)

def process_command(user_id, command, bbs_system):
    """Handle commands for the Tic Tac Toe game."""
    if user_id not in bbs_system.users:
        bbs_system.users[user_id] = {}

    user_state = bbs_system.users[user_id]

    # Initialize or reset the game based on mode selection
    if "tic_tac_toe" not in user_state:
        if command == "1":
            user_state["tic_tac_toe"] = init_game("pvp")
            return f"Player vs Player mode selected.\n\n{render_board(user_state['tic_tac_toe']['board'])}\n\nX starts. Enter 1-9 to make your move."
        elif command == "2":
            user_state["tic_tac_toe"] = init_game("pvc")
            return f"Player vs Computer mode selected.\n\n{render_board(user_state['tic_tac_toe']['board'])}\n\nX starts. Enter 1-9 to make your move."
        elif command.strip().lower() == "cd ..":
            bbs_system.users[user_id]["menu"].pop()
            return bbs_system.display_menu(user_id)
        else:
            return "Invalid choice. Enter '1' for Player vs Player, '2' for Player vs Computer, or 'cd ..' to exit."

    game = user_state["tic_tac_toe"]

    if command.strip().lower() == "cd ..":
        bbs_system.users[user_id]["menu"].pop()
        return bbs_system.display_menu(user_id)

    if game["winner"]:
        return f"The game is over! Winner: {game['winner']}\n\n{render_board(game['board'])}\n\nType 'cd ..' to return to the main menu."

    try:
        position = int(command) - 1  # Convert input to board index
        if position < 0 or position > 8:
            return "Invalid move! Choose a number between 1 and 9."
        if game["board"][position] != " ":
            return "That spot is already taken. Choose another."

        # Player move
        game["board"][position] = game["current_player"]
        game["turns"] += 1

        # Check for a winner
        winner = check_winner(game["board"])
        if winner:
            game["winner"] = winner
            return f"{render_board(game['board'])}\n\nCongratulations! {winner} wins!\n\nType 'cd ..' to return to the main menu."
        elif game["turns"] == 9:  # Check for a draw
            return f"{render_board(game['board'])}\n\nIt's a draw!\n\nType 'cd ..' to return to the main menu."

        # Switch players or let the computer move
        if game["mode"] == "pvp":
            game["current_player"] = "O" if game["current_player"] == "X" else "X"
            return f"{render_board(game['board'])}\n\nNext turn: {game['current_player']}"
        elif game["mode"] == "pvc":
            game["current_player"] = "O"
            computer_pos = computer_move(game["board"])
            game["board"][computer_pos] = "O"
            game["turns"] += 1

            # Check for a winner after the computer's move
            winner = check_winner(game["board"])
            if winner:
                game["winner"] = winner
                return f"{render_board(game['board'])}\n\nComputer wins!\n\nType 'cd ..' to return to the main menu."
            elif game["turns"] == 9:
                return f"{render_board(game['board'])}\n\nIt's a draw!\n\nType 'cd ..' to return to the main menu."

            game["current_player"] = "X"
            return f"{render_board(game['board'])}\n\nYour turn: X"
    except ValueError:
        return "Invalid input! Enter a number between 1 and 9."
