"""Client for the remote Laya host server (Jev-pattern typed decisions over HTTP).

The Laya host is the ONLY runtime Laya backend (user decision, 2026-09-25:
always use the remote Laya host). Contract measured 2026-09-24 (see
logs/run-2026-09-24-laya-smoke.md):

    POST /predict  {"state": {...}, "questions": {name: {type, instructions, criteria}}}
    GET  /health   -> {"status": "ok", ...}

Response (logged in full by callers):
    {"model", "answers": {name: {type, ...}}, "routing", "usage", "_server_ms"}

Mica (2026-09-27, user direction — A/B engine; doc/research-mica.md):
    POST /v1/systemone (alias /v1/decide), same request/answer shapes,
    response carries "latency_ms" instead of "_server_ms" and no "routing";
    MicaClient normalizes latency_ms -> _server_ms. LayaClient (path
    /predict, :8002) stays the default; MicaClient (:8010) is opt-in.

Question shapes (Laya host):
    choice: {"type": "choice", "instructions": str, "criteria": {label: description}}
    score:  {"type": "score",  "instructions": str, "criteria": [label, ...]}
    noul:   {"type": "noul",   "instructions": str}

Failure model (drives the harness degraded mode, requirements-decisions S10):
    - LayaUnavailableError: connection refused / timeout / 5xx  -> "Laya absent" frames
    - LayaProtocolError:    200 but malformed/invalid answer     -> treated as a bad
      answer (discarded; harness holds last macro)

Stdlib only (urllib) — no extra deps in the venv.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8002"
MICA_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_PREDICT_PATH = "/predict"
MICA_PREDICT_PATH = "/v1/systemone"


class LayaError(RuntimeError):
    """Base class for Laya client errors."""


class LayaUnavailableError(LayaError):
    """Tunnel/server unreachable (connection refused, timeout, HTTP 5xx)."""


class LayaProtocolError(LayaError):
    """Server answered but the payload is malformed or a question is invalid."""


def _validate_answer(name, qtype, answer):
    if not isinstance(answer, dict):
        raise LayaProtocolError(f"answer {name!r} is not an object: {type(answer)}")
    if qtype == "choice":
        choice = answer.get("choice")
        probs = answer.get("probabilities") or {}
        if not isinstance(choice, str) or choice not in probs:
            raise LayaProtocolError(
                f"choice answer {name!r}: choice={choice!r} not in probabilities")
    elif qtype == "score":
        if not isinstance(answer.get("score"), (int, float)):
            raise LayaProtocolError(f"score answer {name!r} missing float 'score'")
        if not isinstance(answer.get("probabilities"), dict):
            raise LayaProtocolError(f"score answer {name!r} missing probabilities")
    elif qtype == "noul":
        if not isinstance(answer.get("noul"), (int, float)):
            raise LayaProtocolError(f"noul answer {name!r} missing float 'noul'")
    else:
        raise LayaProtocolError(f"unknown question type {qtype!r} for {name!r}")


class LayaClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT_S,
                 predict_path: str = DEFAULT_PREDICT_PATH):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.predict_path = predict_path

    # -- low-level -------------------------------------------------------------
    def _post(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read()
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600:
                raise LayaUnavailableError(f"HTTP {e.code} from {path}") from e
            raise LayaProtocolError(f"HTTP {e.code} from {path}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LayaUnavailableError(f"{path}: {e}") from e
        except json.JSONDecodeError as e:
            raise LayaProtocolError(f"non-JSON response from {path}") from e

    # -- API -------------------------------------------------------------------
    def health(self) -> dict:
        """GET /health. Returns the health dict, or raises LayaUnavailableError."""
        req = urllib.request.Request(self.base_url + "/health", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LayaUnavailableError(f"/health: {e}") from e

    def is_available(self) -> bool:
        try:
            h = self.health()
        except LayaUnavailableError:
            return False
        return h.get("status") == "ok"

    def predict(self, state, questions: dict, model: str | None = None,
                lang: str | None = None) -> dict:
        """One batched decision call.

        state: dict (or str) — the compact text state.
        questions: {name: {type, instructions, criteria}}
        Returns the full response dict (including routing/usage/_server_ms).
        Raises LayaUnavailableError / LayaProtocolError.
        """
        payload = {"state": state, "questions": questions}
        if model:
            payload["model"] = model
        if lang:
            payload["lang"] = lang

        t0 = time.perf_counter()
        resp = self._post(self.predict_path, payload)
        wall_ms = (time.perf_counter() - t0) * 1000.0

        # Mica reports server time as 'latency_ms' (and omits 'routing');
        # normalize so trace logging (agent.py) works for both engines.
        if "_server_ms" not in resp and "latency_ms" in resp:
            resp["_server_ms"] = resp["latency_ms"]

        answers = resp.get("answers")
        if not isinstance(answers, dict):
            raise LayaProtocolError(f"response missing 'answers': {str(resp)[:300]}")
        for name, q in questions.items():
            if name not in answers:
                raise LayaProtocolError(f"response missing answer for {name!r}")
            _validate_answer(name, q.get("type"), answers[name])

        # attach wall time for logging (server-side time is resp["_server_ms"])
        resp["_wall_ms"] = wall_ms
        return resp

    def choice(self, state, name: str, q: dict) -> tuple[str, dict]:
        """Convenience: single choice question -> (label, full answer dict)."""
        resp = self.predict(state, {name: q})
        a = resp["answers"][name]
        return a["choice"], a

    def noul(self, state, name: str, q: dict) -> tuple[float, dict]:
        """Convenience: single noul question -> (P(true), full answer dict)."""
        resp = self.predict(state, {name: q})
        a = resp["answers"][name]
        return float(a["noul"]), a


class MicaClient(LayaClient):
    """Client for the Mica server on the Laya host (mica-v0.1-4b, :8010).

    Jev-pattern decision model speaking the TypeSafe /v1/systemone format —
    the same request/answer contract as Laya (choice/score/noul, measured
    2026-09-27, doc/research-mica.md), so validation and the harness answer
    parsing are shared. Differences handled here:
      * decision path is /v1/systemone (alias /v1/decide), not /predict
      * server time arrives as 'latency_ms' -> normalized to '_server_ms'
      * inputs > 8,192 tokens are rejected (HTTP 400) — the R4.6-compacted
        state (<= 2048 tokens) is far below the cap
    """

    def __init__(self, base_url: str = MICA_BASE_URL, timeout: float = DEFAULT_TIMEOUT_S):
        super().__init__(base_url, timeout, predict_path=MICA_PREDICT_PATH)
