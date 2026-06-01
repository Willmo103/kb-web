"""
Gunicorn runner script for production deployments of `kb-web`.
Spawns Gunicorn on POSIX-compliant systems and falls back to Uvicorn on Windows.
"""

import sys
import multiprocessing

try:
    import gunicorn.app.base
    GUNICORN_AVAILABLE = True
except ImportError:
    GUNICORN_AVAILABLE = False

if sys.platform != "win32" and GUNICORN_AVAILABLE:
    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        """
        Custom programmatic Gunicorn application launcher wrapper.
        """
        def __init__(self, app_uri: str, options: dict = None):
            self.options = options or {}
            self.app_uri = app_uri
            super().__init__()

        def load_config(self):
            config = {key: value for key, value in self.options.items()
                      if key in self.cfg.settings and value is not None}
            for key, value in config.items():
                self.cfg.set(key.lower(), value)

        def load(self):
            # Dynamic import of ASGI app to prevent circular dependency issues
            from importlib import import_module
            module_path, app_name = self.app_uri.split(":")
            module = import_module(module_path)
            return getattr(module, app_name)
else:
    class StandaloneApplication:
        def __init__(self, app_uri: str, options: dict = None):
            pass
        def run(self):
            raise NotImplementedError("Gunicorn is not supported on Windows or non-POSIX platforms.")


def run_server(app_uri: str, host: str, port: int, workers: int = None, reload: bool = False) -> None:
    """
    Launches the web application. Utilizes Gunicorn with Uvicorn workers in production,
    falling back to Uvicorn directly if Windows or hot-reloading is requested.
    """
    if sys.platform == "win32" or reload or not GUNICORN_AVAILABLE:
        import uvicorn
        print(f"Starting server using Uvicorn on http://{host}:{port} (reload={reload})")
        uvicorn.run(app_uri, host=host, port=port, reload=reload)
    else:
        if workers is None:
            # Standard Gunicorn sizing recommendation
            workers = (multiprocessing.cpu_count() * 2) + 1
        
        options = {
            'bind': f'{host}:{port}',
            'workers': workers,
            'worker_class': 'uvicorn.workers.UvicornWorker',
            'loglevel': 'info',
        }
        print(f"Starting production server using Gunicorn on http://{host}:{port} (workers={workers})")
        StandaloneApplication(app_uri, options).run()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the production Gunicorn/Uvicorn server.")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--port", type=int, default=8050, help="Binding port")
    parser.add_argument("--workers", type=int, default=None, help="Number of Gunicorn workers")
    parser.add_argument("--reload", action="store_true", help="Use hot-reload (Uvicorn only)")
    parser.add_argument("--app-uri", default="kb_web.server:app", help="ASGI Application URI")
    args = parser.parse_args()

    run_server(args.app_uri, args.host, args.port, args.workers, args.reload)
