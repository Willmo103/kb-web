import sys
from pathlib import Path
from alembic.config import Config
from alembic import command

def deploy():
    project_dir = Path(__file__).resolve().parent.parent
    ini_path = project_dir / "alembic.ini"
    
    print(f"[INFO] Running database migrations using: {ini_path}")
    alembic_cfg = Config(str(ini_path))
    
    # Run the Alembic upgrade command to apply all pending revisions
    command.upgrade(alembic_cfg, "head")
    print("[SUCCESS] Database migrations deployed successfully!")

if __name__ == "__main__":
    deploy()
