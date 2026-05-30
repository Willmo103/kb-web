"""Knowledge Base Web Importer.

Provides the web UI dashboard, share target listener, and database backup
importer tools for the kb project stack.
"""

from .cli import app


def main() -> None:
    """Console script entrypoint.

    Invokes the Typer CLI commander.
    """
    app()
