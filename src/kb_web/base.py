"""
Base shared dependencies, configuration, and route guards for kb-web.
"""

import time
import hashlib
import hmac
import threading
import jinja2
import ollama
import sqlite_utils
import logging
from contextlib import contextmanager
from typing import Optional
from urllib.parse import quote_plus, urlparse
from fastapi import Request, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import Config
from .db import init_db

# Instantiate global configuration
config = Config()


def extract_url_path(url: str) -> str:
    try:
        parsed = urlparse(url)
        path = parsed.path
        if not path or path == "/":
            return parsed.netloc or url
        return path
    except Exception:
        return url


# Set up Jinja2 environment utilizing PackageLoader for clean packaging with autoescape enabled
_jinja_env = jinja2.Environment(
    loader=jinja2.PackageLoader("kb_web", "templates"),
    autoescape=jinja2.select_autoescape(["html", "xml", "j2.html", "html5"]),
)
_jinja_env.filters["urlpath"] = extract_url_path
_jinja_env.globals["config"] = config

COOKIE_NAME = "kb_session"
SESSION_EXPIRATION_SECONDS = 3600 * 24  # 24 hours


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler that writes logs to the database using SQLAlchemy."""
    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    def emit(self, record: logging.LogRecord) -> None:
        # Skip logging if it is from sqlalchemy engine to avoid infinite recursion/loops,
        # or alembic/plugins to avoid startup migration spam in system logs.
        if (
            record.name.startswith("sqlalchemy")
            or record.name.startswith("alembic")
            or record.module == "plugins"
        ):
            return

        try:
            from datetime import datetime
            import traceback

            # Format the message
            msg = self.format(record)

            # Format traceback if present
            tb = ""
            if record.exc_info:
                tb = "".join(traceback.format_exception(*record.exc_info))

            from .models_orm import SystemLog
            with db_session() as session:
                log_entry = SystemLog(
                    timestamp=datetime.now().isoformat(),
                    level=record.levelname,
                    module=record.module,
                    message=msg,
                    traceback=tb,
                )
                session.add(log_entry)
        except Exception:
            # Prevent logging errors from crashing the application
            pass


SQLiteLogHandler = DatabaseLogHandler
DatabaseLogHandler = DatabaseLogHandler


_local = threading.local()
_init_lock = threading.Lock()
_db_initialized = False


def _get_db() -> sqlite_utils.Database:
    """Helper dependency to retrieve a clean database handle."""
    global _db_initialized
    db_path = config.db_path
    db = getattr(_local, "db", None)
    db_path_cached = getattr(_local, "db_path", None)
    if db is None or db_path_cached != db_path:
        import sqlite3

        conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        db = sqlite_utils.Database(conn)
        if not _db_initialized:
            with _init_lock:
                if not _db_initialized:
                    init_db(db, config)
                    _db_initialized = True
        _local.db = db
        _local.db_path = db_path
    return db


# --- SQLAlchemy / ORM Connection Dialect and Engine Setup ---

_engine = None
_SessionFactory = None
_db_lock = threading.Lock()


def get_engine():
    global _engine, _SessionFactory
    if _engine is None:
        with _db_lock:
            if _engine is None:
                db_url = config.database_url
                if db_url:
                    # Clean up PostgreSQL URL prefix if necessary
                    if db_url.startswith("postgres://"):
                        db_url = db_url.replace(
                            "postgres://", "postgresql+psycopg2://", 1
                        )
                    elif db_url.startswith("postgresql://") and not db_url.startswith(
                        "postgresql+psycopg2://"
                    ):
                        db_url = db_url.replace(
                            "postgresql://", "postgresql+psycopg2://", 1
                        )

                    _engine = create_engine(
                        db_url,
                        pool_size=10,
                        max_overflow=20,
                        pool_pre_ping=True,
                        pool_recycle=300,
                        connect_args={"connect_timeout": 5},
                    )

                    # Ensure pgvector extension is created on startup
                    from sqlalchemy import text

                    try:
                        with _engine.connect() as conn:
                            with conn.begin():
                                try:
                                    conn.execute(
                                        text("CREATE EXTENSION IF NOT EXISTS vector;")
                                    )
                                except Exception as e:
                                    print(
                                        f"Warning: Failed to create pgvector extension: {e}"
                                    )
                    except Exception as e:
                        print(f"Warning: Initial database connection during engine startup deferred: {e}")
                else:
                    _engine = create_engine(
                        f"sqlite:///{config.db_path}",
                        connect_args={"timeout": 30.0, "check_same_thread": False},
                    )

                # Import models and create all tables if missing
                from .models_orm import Base, ensure_views_and_indexes

                Base.metadata.create_all(_engine)
                ensure_views_and_indexes(_engine)
                _SessionFactory = sessionmaker(bind=_engine)
                try:
                    from .agent_config import ensure_default_agent_configs
                    ensure_default_agent_configs()
                except Exception as _cfg_err:
                    print(f"Warning: Default agent configurations check deferred: {_cfg_err}")
    return _engine


@contextmanager
def db_session():
    """Context manager for SQLAlchemy ORM session lifecycle management."""
    get_engine()
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class LoggedOllamaClient:
    """A wrapper for ollama.Client that logs call details, duration, and responses/errors
    to the SQLite database table `ollama_logs` and enforces a connection timeout.
    """

    def __init__(self, host: str, timeout: Optional[float] = None) -> None:
        if timeout is None:
            timeout = getattr(config, "ollama_timeout", 1200.0)
        self._client = ollama.Client(host=host, timeout=timeout)
        self.host = host
        self.timeout = timeout

    def pull(self, *args, **kwargs):
        return self._client.pull(*args, **kwargs)

    def push(self, *args, **kwargs):
        return self._client.push(*args, **kwargs)

    def list(self, *args, **kwargs):
        return self._client.list(*args, **kwargs)

    def chat(self, *args, **kwargs):
        import traceback

        # Determine prompt type
        prompt_type = "chat"
        messages = kwargs.get("messages", [])
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                content = str(m.get("content", "")).lower()
                if "taxonomist" in content or "categorize" in content:
                    prompt_type = "taxonomy"
                elif "wiki" in content:
                    prompt_type = "wiki"
                elif "taste" in content:
                    prompt_type = "taste"
                elif "rag" in content or "context" in content:
                    prompt_type = "rag"

        model = kwargs.get("model", "")
        options = {k: v for k, v in kwargs.items() if k not in ("model", "messages")}

        start_time = time.time()
        try:
            resp = self._client.chat(*args, **kwargs)
            duration = time.time() - start_time

            # Retrieve content response safely
            response_content = ""
            if hasattr(resp, "message") and hasattr(resp.message, "content"):
                response_content = resp.message.content
            elif (
                isinstance(resp, dict)
                and "message" in resp
                and "content" in resp["message"]
            ):
                response_content = resp["message"]["content"]
            else:
                response_content = str(resp)

            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=messages,
                options=options,
                response=response_content,
                duration=duration,
                status="success",
            )
            return resp
        except Exception as e:
            duration = time.time() - start_time
            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=messages,
                options=options,
                response=f"Error: {e}\n{traceback.format_exc()}",
                duration=duration,
                status="failed",
            )
            raise e

    def embeddings(self, *args, **kwargs):
        import traceback

        prompt_type = "embeddings"
        model = kwargs.get("model", "")
        prompt = kwargs.get("prompt", "")
        options = {k: v for k, v in kwargs.items() if k not in ("model", "prompt")}

        start_time = time.time()
        try:
            resp = self._client.embeddings(*args, **kwargs)
            duration = time.time() - start_time

            emb_vector = (
                resp.get("embedding", [])
                if isinstance(resp, dict)
                else getattr(resp, "embedding", [])
            )
            response_content = f"Success (vector dim: {len(emb_vector)})"

            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt[:200] + "..."
                        if len(prompt) > 200
                        else prompt,
                    }
                ],
                options=options,
                response=response_content,
                duration=duration,
                status="success",
            )
            return resp
        except Exception as e:
            duration = time.time() - start_time
            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt[:200] + "..."
                        if len(prompt) > 200
                        else prompt,
                    }
                ],
                options=options,
                response=f"Error: {e}\n{traceback.format_exc()}",
                duration=duration,
                status="failed",
            )
            raise e

    def generate(self, *args, **kwargs):
        import traceback

        prompt_type = "generate"
        model = kwargs.get("model", "")
        prompt = kwargs.get("prompt", "")
        options = {k: v for k, v in kwargs.items() if k not in ("model", "prompt")}

        start_time = time.time()
        try:
            resp = self._client.generate(*args, **kwargs)
            duration = time.time() - start_time

            response_content = ""
            if hasattr(resp, "response"):
                response_content = resp.response
            elif isinstance(resp, dict) and "response" in resp:
                response_content = resp["response"]
            else:
                response_content = str(resp)

            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt[:500] if len(prompt) > 500 else prompt,
                    }
                ],
                options=options,
                response=response_content,
                duration=duration,
                status="success",
            )
            return resp
        except Exception as e:
            duration = time.time() - start_time
            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt[:500] if len(prompt) > 500 else prompt,
                    }
                ],
                options=options,
                response=f"Error: {e}\n{traceback.format_exc()}",
                duration=duration,
                status="failed",
            )
            raise e

    def systemone(self, *args, **kwargs):
        """Native systemone decision routing method for d1, tev1, and nimble models."""
        import traceback

        prompt_type = "systemone"
        model = kwargs.get("model", "d1")
        state = kwargs.get("state", "")
        raw_questions = kwargs.get("questions", {})
        
        # Normalize questions mapping to Ollama /v1/systemone specification (instructions, type, criteria)
        normalized_questions = {}
        if isinstance(raw_questions, dict):
            for q_name, q_val in raw_questions.items():
                if isinstance(q_val, dict):
                    q_copy = dict(q_val)
                    if "question" in q_copy and "instructions" not in q_copy:
                        q_copy["instructions"] = q_copy.pop("question")
                    if "choices" in q_copy and "criteria" not in q_copy:
                        q_copy["criteria"] = q_copy.pop("choices")
                    if q_copy.get("type") in ("probability", "bool", "boolean"):
                        q_copy["type"] = "noul"
                    normalized_questions[q_name] = q_copy
                else:
                    normalized_questions[q_name] = q_val
        else:
            normalized_questions = raw_questions

        # Strip any LLM chat options before calling systemone
        clean_kwargs = {
            "model": model,
            "state": state,
            "questions": normalized_questions,
        }
        if "keep_alive" in kwargs and kwargs["keep_alive"] is not None:
            clean_kwargs["keep_alive"] = kwargs["keep_alive"]

        options = {
            k: v
            for k, v in kwargs.items()
            if k not in ("model", "state", "questions", "keep_alive")
        }

        start_time = time.time()
        try:
            if hasattr(self._client, "systemone"):
                resp = self._client.systemone(**clean_kwargs)
            else:
                import httpx
                http_resp = httpx.post(
                    f"{self.host.rstrip('/')}/v1/systemone",
                    json=clean_kwargs,
                    timeout=self.timeout or 120.0,
                )
                http_resp.raise_for_status()
                resp = http_resp.json()

            duration = time.time() - start_time
            response_content = str(getattr(resp, "answers", resp))

            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"State: {str(state)[:300]}... Questions: {list(normalized_questions.keys()) if isinstance(normalized_questions, dict) else str(normalized_questions)[:100]}",
                    }
                ],
                options=options,
                response=response_content,
                duration=duration,
                status="success",
            )
            return resp
        except Exception as e:
            duration = time.time() - start_time
            self._log_call(
                prompt_type=prompt_type,
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"State: {str(state)[:300]}... Questions: {list(questions.keys()) if isinstance(questions, dict) else str(questions)[:100]}",
                    }
                ],
                options=options,
                response=f"Error: {e}\n{traceback.format_exc()}",
                duration=duration,
                status="failed",
            )
            raise e

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _log_call(
        self, prompt_type, model, messages, options, response, duration, status
    ) -> None:
        import json
        from datetime import datetime

        try:
            db = _get_db()
            db["ollama_logs"].insert(
                {
                    "timestamp": datetime.now().isoformat(),
                    "model": model,
                    "prompt_type": prompt_type,
                    "messages": json.dumps(messages),
                    "options": json.dumps(options),
                    "response": response,
                    "duration": duration,
                    "status": status,
                }
            )
            db.conn.commit()
        except Exception as err:
            print(f"Failed to log Ollama call to database: {err}")


def _get_ollama_client(timeout: Optional[float] = None) -> LoggedOllamaClient:
    """Helper to dynamically instantiate the Ollama client based on configured host and timeout."""
    if timeout is None:
        timeout = getattr(config, "ollama_timeout", 1200.0)
    return LoggedOllamaClient(host=config.ollama_host, timeout=timeout)


def _get_session_secret() -> bytes:
    """Derives a cryptographically secure key for session signatures from dedicated session secret."""
    secret_str = getattr(config, "session_secret", None)
    if secret_str:
        return hashlib.sha256(secret_str.encode("utf-8")).digest()
    return hashlib.sha256(config.admin_password.encode("utf-8")).digest()


def generate_session_token(expiry_time: float) -> str:
    """Generates a tamper-proof session token containing the expiration timestamp."""
    import hmac

    payload = str(int(expiry_time))
    secret = _get_session_secret()
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def safe_compare_digest(a: Optional[str], b: Optional[str]) -> bool:
    """Constant-time string comparison safe against non-ASCII input and None types."""
    if a is None or b is None:
        return False
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


def verify_session_token(token: str) -> bool:
    """Verifies a signed token's cryptographic signature and expiration."""
    if not token or "." not in token:
        return False
    try:
        payload, signature = token.split(".", 1)
        expiry_time = int(payload)
        if expiry_time < time.time():
            return False

        secret = _get_session_secret()
        expected_signature = hmac.new(
            secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return safe_compare_digest(signature, expected_signature)
    except Exception:
        return False


def is_request_authenticated(request: Request) -> bool:
    """Checks whether the request is authenticated via session cookie, master API key, or registered CLI API key."""
    # 1. Check session cookie
    token = request.cookies.get(COOKIE_NAME)
    if token and verify_session_token(token):
        return True

    # 2. Check API key (for API endpoints or external tools/extensions)
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key_header = auth_header[7:].strip()
        elif auth_header.startswith("ApiKey "):
            api_key_header = auth_header[7:].strip()
        elif auth_header:
            api_key_header = auth_header.strip()

    if not api_key_header:
        return False

    if config.api_key and safe_compare_digest(api_key_header, config.api_key):
        if config.is_default_api_key and not config.allow_insecure_defaults:
            return False
        return True

    # Check registered CLI API keys in database
    try:
        from .models_orm import CliApiKey
        with db_session() as session:
            key_exists = session.query(CliApiKey).filter_by(key=api_key_header).first() is not None
            if key_exists:
                return True
    except Exception:
        pass

    return False


def verify_auth(request: Request) -> None:
    """Security route guard ensuring requests contain a valid session cookie or API key."""
    if is_request_authenticated(request):
        return
    redirect_url = f"/login?next={quote_plus(str(request.url))}"
    raise HTTPException(status_code=303, headers={"Location": redirect_url})


def verify_api_key(request: Request) -> str:
    """Security guard verifying API Key header matching KB_API_KEY or registered CLI API key."""
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key_header = auth_header[7:].strip()
        elif auth_header.startswith("ApiKey "):
            api_key_header = auth_header[7:].strip()
        elif auth_header:
            api_key_header = auth_header.strip()

    if not api_key_header:
        raise HTTPException(
            status_code=401, detail="Unauthorized: API key required."
        )

    if config.api_key and safe_compare_digest(api_key_header, config.api_key):
        if config.is_default_api_key and not config.allow_insecure_defaults:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Default API key 'kb-secret-key' is disabled for security. Please configure KB_API_KEY.",
            )
        return api_key_header


    try:
        from .models_orm import CliApiKey
        with db_session() as session:
            key_exists = session.query(CliApiKey).filter_by(key=api_key_header).first() is not None
            if key_exists:
                return api_key_header
    except Exception:
        pass

    raise HTTPException(
        status_code=401, detail="Unauthorized: Invalid API key."
    )
