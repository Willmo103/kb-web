import sys
from kb_web.scripts.check_db_ready import wait_for_db

if __name__ == "__main__":
    if not wait_for_db():
        sys.exit(1)
