"""
CLI Module for the Knowledge Base Web Importer application.
"""

import typer

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


@app.command()
def mcp(
    host: str = typer.Option(
        "0.0.0.0", help="The binding host interface address for the MCP server."
    ),
    port: int = typer.Option(
        8051, help="The communication port number to bind the MCP server on."
    ),
    transport: str = typer.Option(
        "sse", help="The transport protocol to use ('stdio' or 'sse')."
    ),
) -> None:
    """Starts the Model Context Protocol (MCP) server for agents to query articles."""
    from .mcp_server import mcp as mcp_server

    typer.echo(f"Starting Knowledge Base MCP server using {transport} transport...")
    if transport == "sse":
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    app()
