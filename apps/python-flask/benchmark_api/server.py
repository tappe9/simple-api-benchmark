"""Single-process Waitress entry point with explicit graceful resource cleanup."""

import signal

from waitress.server import create_server

from benchmark_api.app import create_app
from benchmark_api.database import close_pool, open_pool


def serve() -> None:
    pool = open_pool()
    server = None
    previous = {}
    try:
        app = create_app(pool)
        server = create_server(
            app,
            host="0.0.0.0",
            port=8080,
            threads=1,
            channel_timeout=30,
            cleanup_interval=10,
            asyncore_use_poll=True,
        )

        def stop(_signum, _frame):
            server.close()

        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, stop)
        server.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if server is not None:
            server.close()
            dispatcher = getattr(server, "task_dispatcher", None)
            if dispatcher is not None:
                dispatcher.shutdown(cancel_pending=False, timeout=5)
        close_pool(pool)


if __name__ == "__main__":
    serve()
