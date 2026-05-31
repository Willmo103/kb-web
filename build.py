import subprocess
import sys
from pathlib import Path


def run_step(cmd: list[str], description: str):
    print(f"\n=========================================")
    print(f"Step: {description}")
    print(f"Running: {' '.join(cmd)}")
    print(f"=========================================")
    try:
        # Use shell=True on Windows to support running commands correctly in all shell contexts
        result = subprocess.run(cmd, check=True, shell=sys.platform == "win32")
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Step failed: {description}")
        print(f"Command returned non-zero exit code: {e.returncode}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print(
            f"\n[ERROR] Command not found. Make sure {' '.join(cmd)} is available in path."
        )
        sys.exit(1)


def main():
    project_dir = Path(__file__).resolve().parent

    # 1. Sync project environment
    run_step(["uv", "sync"], "Synchronizing environment & dependencies")

    # 2. Run unit tests
    run_step(["uv", "run", "pytest"], "Running pytest suite")

    # 3. Build packaging artifacts
    run_step(["uv", "build"], "Building source and wheel packages")

    print("\n[SUCCESS] Build pipeline completed successfully!")


if __name__ == "__main__":
    main()
