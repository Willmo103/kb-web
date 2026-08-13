import socket
import time
import sys

def wait_for_db(host="localhost", port=5432, timeout=30):
    start = time.time()
    print(f"Waiting for database at {host}:{port}...")
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                print("Database is ready!")
                return True
        except (socket.timeout, ConnectionRefusedError):
            time.sleep(1)
    print("Database connection timed out.")
    return False

if __name__ == "__main__":
    if not wait_for_db():
        sys.exit(1)
