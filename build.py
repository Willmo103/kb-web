import subprocess
import sys
from pathlib import Path


from typing import Optional

def run_step(cmd: list[str], description: str, cwd: Optional[Path] = None):
    print("\n=========================================")
    print(f"Step: {description}")
    print(f"Running: {' '.join(cmd)}")
    print("=========================================")
    try:
        # Use shell=True on Windows to support running commands correctly in all shell contexts
        subprocess.run(cmd, check=True, shell=sys.platform == "win32", cwd=str(cwd) if cwd else None)
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Step failed: {description}")
        print(f"Command returned non-zero exit code: {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print(
            f"\n[ERROR] Command not found. Make sure {' '.join(cmd)} is available in path."
        )
        sys.exit(1)


def clean_previous_builds():
    import shutil

    project_dir = Path(__file__).resolve().parent

    # 1. Clean project_dir / "dist"
    dist_dir = project_dir / "dist"
    if dist_dir.exists() and dist_dir.is_dir():
        print(f"Cleaning previous build directory: {dist_dir}")
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            print(f"Warning: Failed to clean {dist_dir}: {e}")

    # 2. Clean project_dir / "desktop" / "dist"
    desktop_dist = project_dir / "desktop" / "dist"
    if desktop_dist.exists() and desktop_dist.is_dir():
        print(f"Cleaning previous desktop build directory: {desktop_dist}")
        try:
            shutil.rmtree(desktop_dist)
        except Exception as e:
            print(f"Warning: Failed to clean {desktop_dist}: {e}")

    # 3. Clean project_dir / "kb-web-cli" / "dist"
    cli_dist = project_dir / "kb-web-cli" / "dist"
    if cli_dist.exists() and cli_dist.is_dir():
        print(f"Cleaning previous CLI build directory: {cli_dist}")
        try:
            shutil.rmtree(cli_dist)
        except Exception as e:
            print(f"Warning: Failed to clean {cli_dist}: {e}")


def bootstrap_database():
    import socket
    import time
    
    print("[INFO] Checking if local PostgreSQL is active...")
    try:
        with socket.create_connection(("localhost", 5432), timeout=2):
            print("[INFO] Local PostgreSQL is already running and ready.")
            return
    except (socket.timeout, ConnectionRefusedError):
        pass

    print("[INFO] Local PostgreSQL is not running. Attempting to start service using docker-compose...")
    try:
        res = subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=sys.platform == "win32")
        if res.returncode == 0:
            compose_cmd = ["docker", "compose"]
        else:
            compose_cmd = ["docker-compose"]
        
        project_dir = Path(__file__).resolve().parent
        compose_file = project_dir / ".devcontainer" / "docker-compose.yml"
        if compose_file.exists():
            print(f"[INFO] Booting database stack using: {' '.join(compose_cmd)} -f {compose_file} up -d db")
            subprocess.run(compose_cmd + ["-f", str(compose_file), "up", "-d", "db"], check=True, shell=sys.platform == "win32")
            print("[INFO] Waiting for database connection to be established...")
            for _ in range(30):
                try:
                    with socket.create_connection(("localhost", 5432), timeout=1):
                        print("[INFO] PostgreSQL service is fully online.")
                        return
                except (socket.timeout, ConnectionRefusedError):
                    time.sleep(1)
            print("[ERROR] Timeout waiting for PostgreSQL database startup.")
            sys.exit(1)
        else:
            print("[WARNING] docker-compose.yml not found in .devcontainer/ folder. Cannot auto-start database.")
    except Exception as e:
        print(f"[WARNING] Failed to auto-start database container: {e}")


def main():
    clean_previous_builds()
    bootstrap_database()

    # Detect if uv is available
    has_uv = False
    try:
        res = subprocess.run(["uv", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=sys.platform == "win32")
        if res.returncode == 0:
            has_uv = True
    except FileNotFoundError:
        pass

    project_dir = Path(__file__).resolve().parent
    if has_uv:
        # 1. Sync project environment
        run_step(["uv", "sync"], "Synchronizing environment & dependencies")

        # 2. Run unit tests
        run_step(["uv", "run", "pytest"], "Running pytest suite")

        # 3. Build packaging artifacts
        run_step(["uv", "build"], "Building source and wheel packages")
        run_step(["uv", "build"], "Building CLI submodule source and wheel packages", cwd=project_dir / "kb-web-cli")
    else:
        print("[INFO] 'uv' command not found. Falling back to python/venv tools.")
        
        # Determine executable paths
        python_exe = sys.executable
        if sys.platform == "win32":
            pytest_exe = str(project_dir / ".venv" / "Scripts" / "pytest.exe")
            pip_exe = str(project_dir / ".venv" / "Scripts" / "pip.exe")
        else:
            pytest_exe = str(project_dir / ".venv" / "bin" / "pytest")
            pip_exe = str(project_dir / ".venv" / "bin" / "pip")

        if not Path(pytest_exe).exists():
            pytest_exe = "pytest"

        # 1. Make sure build module is installed if we need to package
        try:
            from build import ProjectBuilder
        except ImportError:
            print("[INFO] Installing 'build' package for packaging...")
            if Path(pip_exe).exists():
                subprocess.run([pip_exe, "install", "build"], check=True, shell=sys.platform == "win32")
            else:
                subprocess.run([python_exe, "-m", "pip", "install", "build"], check=True, shell=sys.platform == "win32")

        # 2. Run unit tests
        run_step([pytest_exe], "Running pytest suite")

        # 3. Build packaging artifacts
        build_cmd = [
            python_exe, "-c",
            "import sys, os; sys.path = [p for p in sys.path if p != os.getcwd() and p != '']; import build.__main__; build.__main__.main(sys.argv[1:])"
        ]
        run_step(build_cmd, "Building source and wheel packages")
        run_step(build_cmd, "Building CLI submodule source and wheel packages", cwd=project_dir / "kb-web-cli")

    # 4. Copy artifacts to ARTIFACTS_ROOT if set
    copy_artifacts()

    print("\n[SUCCESS] Build pipeline completed successfully!")


def get_project_metadata():
    import re

    project_dir = Path(__file__).resolve().parent
    pyproject_path = project_dir / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")

    name_match = re.search(r'name\s*=\s*"([^"]+)"', content)
    version_match = re.search(r'version\s*=\s*"([^"]+)"', content)

    name = name_match.group(1) if name_match else "unknown"
    version = version_match.group(1) if version_match else "0.1.0"
    return name, version


def copy_artifacts():
    import shutil
    import os

    artifacts_root = os.environ.get("ARTIFACTS_ROOT")
    if not artifacts_root:
        print(
            "\n[INFO] ARTIFACTS_ROOT environment variable not set. Skipping artifact copy."
        )
        return

    app_name, version = get_project_metadata()
    target_dir = Path(artifacts_root) / app_name / version

    project_dir = Path(__file__).resolve().parent

    # Copy project_dir / "dist" to target_dir / "dist"
    dist_dir = project_dir / "dist"
    if dist_dir.exists() and dist_dir.is_dir():
        dest_dist = target_dir / "dist"
        dest_dist.mkdir(parents=True, exist_ok=True)
        print(f"Copying build artifacts from {dist_dir} to {dest_dist}...")
        for item in dist_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, dest_dist / item.name)
            elif item.is_dir():
                shutil.copytree(item, dest_dist / item.name, dirs_exist_ok=True)

    # Copy project_dir / "desktop" / "dist" to target_dir / "desktop" / "dist"
    desktop_dist_dir = project_dir / "desktop" / "dist"
    if desktop_dist_dir.exists() and desktop_dist_dir.is_dir():
        dest_desktop = target_dir / "desktop" / "dist"
        dest_desktop.mkdir(parents=True, exist_ok=True)
        print(f"Copying desktop artifacts from {desktop_dist_dir} to {dest_desktop}...")
        for item in desktop_dist_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, dest_desktop / item.name)
            elif item.is_dir():
                shutil.copytree(item, dest_desktop / item.name, dirs_exist_ok=True)

    # Copy project_dir / "kb-web-cli" / "dist" to target_dir / "kb-web-cli" / "dist"
    cli_dist_dir = project_dir / "kb-web-cli" / "dist"
    if cli_dist_dir.exists() and cli_dist_dir.is_dir():
        dest_cli = target_dir / "kb-web-cli" / "dist"
        dest_cli.mkdir(parents=True, exist_ok=True)
        print(f"Copying CLI artifacts from {cli_dist_dir} to {dest_cli}...")
        for item in cli_dist_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, dest_cli / item.name)
            elif item.is_dir():
                shutil.copytree(item, dest_cli / item.name, dirs_exist_ok=True)


if __name__ == "__main__":
    main()
