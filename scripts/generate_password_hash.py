#!/usr/bin/env python3
"""
Generate a bcrypt password hash for Techne staff authentication.

Usage:
    python scripts/generate_password_hash.py

Then set the output as the TECHNE_STAFF_PASSWORD_HASH environment variable.
"""
import getpass
import bcrypt


def main():
    print("Technē Dental Staff Password Hash Generator")
    print("=" * 50)
    print()
    
    password = getpass.getpass("Enter password: ")
    password_confirm = getpass.getpass("Confirm password: ")
    
    if password != password_confirm:
        print("Error: Passwords do not match!")
        return 1
    
    if len(password) < 8:
        print("Error: Password must be at least 8 characters long!")
        return 1
    
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode(), salt)
    
    print()
    print("Generated password hash:")
    print("-" * 50)
    print(password_hash.decode())
    print("-" * 50)
    print()
    print("Set this environment variable:")
    print(f'TECHNE_STAFF_PASSWORD_HASH="{password_hash.decode()}"')
    print()
    
    return 0


if __name__ == "__main__":
    exit(main())
