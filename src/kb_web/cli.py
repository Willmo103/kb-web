"""
CLI Module for the Knowledge Base Web Importer application.
"""

import typer
import uvicorn

app = typer.Typer(
    help="CLI management command station for the Knowledge Base Web Importer.",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0", help="The binding host interface address for the web server."
    ),
    port: int = typer.Option(
        8050, help="The communication port number to bind the server on."
    ),
    reload: bool = typer.Option(
        False, help="Toggle hot-reloading for development environments."
    ),
) -> None:
    """Launches the FastAPI web interface and ingestion API server under uvicorn.

    Args:
        host (str): String address representing host.
        port (int): Port integer value.
        reload (bool): Flag defining hot-reload state.
    """
    # Import runner inside function block to ensure rapid CLI startup execution
    from .gunicorn_runner import run_server

    run_server("kb_web.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
