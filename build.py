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
        subprocess.run(
            cmd,
            check=True,
            shell=sys.platform == "win32",
            cwd=str(cwd) if cwd else None,
        )
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

    for rel_path in ["dist", "desktop/dist", "kb-web-cli/dist"]:
        target = project_dir / rel_path
        if target.exists() and target.is_dir():
            print(f"Cleaning previous build directory: {target}")
            try:
                shutil.rmtree(target)
            except Exception as e:
                print(f"Warning: Failed to clean {target}: {e}")


def main():
    clean_previous_builds()

    # Detect if uv is available
    has_uv = False
    try:
        res = subprocess.run(
            ["uv", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=sys.platform == "win32",
        )
        if res.returncode == 0:
            has_uv = True
    except FileNotFoundError:
        pass

    project_dir = Path(__file__).resolve().parent
    if has_uv:
        # 1. Sync project environment
        run_step(["uv", "sync"], "Synchronizing environment & dependencies")

        # 2. Run unit tests
        run_step(["uv", "run", "pytest", "-k", "not test_extension"], "Running pytest suite")
    else:
        print("[INFO] 'uv' command not found. Falling back to python/venv tools.")
        if sys.platform == "win32":
            pytest_exe = str(project_dir / ".venv" / "Scripts" / "pytest.exe")
        else:
            pytest_exe = str(project_dir / ".venv" / "bin" / "pytest")

        if not Path(pytest_exe).exists():
            pytest_exe = "pytest"

        run_step([pytest_exe, "-k", "not test_extension"], "Running pytest suite")

    print("\n[SUCCESS] Build verification pipeline completed successfully!")


if __name__ == "__main__":
    main()

