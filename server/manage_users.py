import sys
import getpass
from auth import init_db, add_user

def main():
    # Ensure the database exists
    init_db()

    if len(sys.argv) < 3 or sys.argv[1] != "add":
        print("Usage: python server/manage_users.py add <username>")
        sys.exit(1)

    username = sys.argv[2]
    
    # Securely prompt for the password (it won't show on screen)
    password = getpass.getpass(f"Enter password for {username}: ")
    
    if add_user(username, password):
        print(f"User '{username}' added successfully!")
    else:
        print(f"Error: User '{username}' already exists.")

if __name__ == "__main__":
    main()
