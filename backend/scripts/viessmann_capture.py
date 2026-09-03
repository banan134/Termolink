#!/usr/bin/env python
"""Stage 0 helper (docs/13 §Etap 0, docs/01 §9): capture real Viessmann API responses as fixtures.

Runs on the host with plain Python 3.12 (stdlib only — no Docker, no Django). It:
  1. performs OAuth2 Authorization Code + PKCE with the Viessmann IdP (docs/01 §2),
     listening for the redirect on http://localhost:8765/oauth/viessmann/callback by default
     (register exactly this URI in the Viessmann developer portal, or pass --redirect-uri with
     any http://localhost:<port>/... URI that is already registered),
  2. records token lifetimes (`expires_in`, whether the refresh token rotates),
  3. downloads GET /equipment/installations?includeGateways=true and, for every device,
     GET …/features, and writes anonymised JSON fixtures to backend/tests/fixtures/viessmann/,
  4. optionally probes a single non-executable/harmless command and records the raw error
     shapes (401 after token invalidation, 404 on a missing endpoint),
  5. writes a capture report (capture_report.json) with HTTP codes, headers and timings —
     that report answers the [ZAŁOŻENIE] items in docs/01.

Usage:
  python backend/scripts/viessmann_capture.py --client-id <ID> [--out DIR] [--probe-limit N]
                                             [--probe-limit N] [--label <name>]

--probe-limit N  issue N extra /features calls in a loop to observe the rate-limit response
                 (careful: this consumes the shared 1450/24 h budget; use on a test account).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUTH_URL = "https://iam.viessmann-climatesolutions.com/idp/v3/authorize"
TOKEN_URL = "https://iam.viessmann-climatesolutions.com/idp/v3/token"  # noqa: S105 — endpoint, not a secret
API_HOST = "https://api.viessmann-climatesolutions.com"
API_BASE = f"{API_HOST}/iot/v2"  # /iot/v1 answered 410 GONE on 2026-09-03 (sunset 2025-12-15)
SCOPE = "IoT User offline_access"
DEFAULT_REDIRECT_URI = "http://localhost:8765/oauth/viessmann/callback"

SERIAL_RE = re.compile(r"\b[0-9]{16}\b")  # Viessmann gateway/device serials are 16 digits
# PII in installation/gateway objects (docs/08 §Prywatność): dropped or replaced, never kept.
PII_KEYS = {
    "address",
    "geolocation",
    "buildingName",
    "buildingEmail",
    "buildingPhone",
    "servicedBy",
}
PII_TEXT_KEYS = {"description"}


def collect_installation_ids(payload: object, mapping: dict[str, str]) -> None:
    """Installation ids are short integers — register them so every occurrence is replaced."""
    data: Any = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return
    for inst in data:
        if isinstance(inst, dict) and inst.get("id") is not None:
            mapping.setdefault(str(inst["id"]), f"9{len(mapping) + 1:06d}")


def anonymise(obj: object, mapping: dict[str, str], parent_key: str | None = None) -> object:
    """Replace serials/installation ids consistently; drop address & building PII."""
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            if k in PII_KEYS:
                out[k] = None
            elif k in PII_TEXT_KEYS and isinstance(v, str) and v:
                out[k] = "ANON"
            else:
                out[k] = anonymise(v, mapping, k)
        return out
    if isinstance(obj, list):
        return [anonymise(v, mapping, parent_key) for v in obj]
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            key = m.group(0)
            mapping.setdefault(key, f"ANON{len(mapping) + 1:04d}{'0' * (16 - 8)}")
            return mapping[key]

        text = SERIAL_RE.sub(repl, obj)
        for raw, anon in mapping.items():
            if raw.isdigit() and len(raw) < 16 and raw in text:
                text = re.sub(rf"(?<![0-9]){re.escape(raw)}(?![0-9])", anon, text)
        return text
    if isinstance(obj, int) and not isinstance(obj, bool) and str(obj) in mapping:
        return int(mapping[str(obj)])
    return obj


def sanitize_directory(out: Path) -> None:
    """Re-anonymise every fixture + the report in place (idempotent)."""
    mapping_file = out / "serial_mapping.json"
    mapping: dict[str, str] = (
        json.loads(mapping_file.read_text(encoding="utf-8")) if mapping_file.exists() else {}
    )
    inst = out / "installations.json"
    if inst.exists():
        doc = json.loads(inst.read_text(encoding="utf-8"))
        collect_installation_ids(doc.get("body", doc), mapping)
    for path in sorted(out.glob("*.json")):
        if path.name == "serial_mapping.json":
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(
            json.dumps(anonymise(doc, mapping), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("  sanitised", path.name)
    mapping_file.write_text(json.dumps(mapping, indent=2), encoding="utf-8")


class Capture:
    def __init__(self, client_id: str, out: Path, label: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.hostname not in ("localhost", "127.0.0.1") or not parsed.port:
            sys.exit("--redirect-uri musi wskazywać http://localhost:<port>/... (nasłuch lokalny)")
        self.listen_port = parsed.port
        self.out = out
        self.label = label
        self.calls: list[dict[str, Any]] = []
        self.report: dict[str, Any] = {
            "captured_at": datetime.now(UTC).isoformat(),
            "calls": self.calls,
        }
        self.tokens: dict[str, Any] = {}
        self.mapping: dict[str, str] = {}

    # ---------------- OAuth ----------------
    def authorize(self) -> None:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(16)
        url = (
            AUTH_URL
            + "?"
            + urllib.parse.urlencode(
                {
                    "response_type": "code",
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "scope": SCOPE,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                }
            )
        )
        print("Otwieram przeglądarkę — zaloguj się kontem ViCare klienta.\n", url, "\n")
        webbrowser.open(url)
        code = self._wait_for_code(state)
        started = time.time()
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "code": code,
                "code_verifier": verifier,
            }
        ).encode()
        status, headers, payload = self._request("POST", TOKEN_URL, body, form=True)
        self._log("token_exchange", TOKEN_URL, status, headers, started, redact=True)
        if status != 200:
            sys.exit(f"token exchange failed: {status} {payload}")
        self.tokens = json.loads(payload)
        self.report["token"] = {
            "expires_in": self.tokens.get("expires_in"),
            "scope": self.tokens.get("scope"),
            "token_type": self.tokens.get("token_type"),
            "has_refresh_token": "refresh_token" in self.tokens,
            "keys": sorted(self.tokens.keys()),
        }
        print("Token OK; expires_in =", self.tokens.get("expires_in"))

    def refresh(self) -> None:
        old = self.tokens.get("refresh_token")
        if not old:
            self.report["refresh"] = "no refresh_token returned"
            return
        started = time.time()
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "client_id": self.client_id, "refresh_token": old}
        ).encode()
        status, headers, payload = self._request("POST", TOKEN_URL, body, form=True)
        self._log("token_refresh", TOKEN_URL, status, headers, started, redact=True)
        if status == 200:
            new = json.loads(payload)
            self.report["refresh"] = {
                "status": status,
                "expires_in": new.get("expires_in"),
                "refresh_token_rotates": bool(new.get("refresh_token"))
                and new.get("refresh_token") != old,
            }
            self.tokens = {**self.tokens, **new}
        else:
            self.report["refresh"] = {"status": status, "body": payload[:500]}
        print("Refresh:", self.report["refresh"])

    def _wait_for_code(self, expected_state: str) -> str:
        result: dict[str, str] = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                result["code"] = query.get("code", [""])[0]
                result["state"] = query.get("state", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>Termolink: autoryzacja OK, wróć do terminala.</h2>".encode())

            def log_message(self, *args: object) -> None:  # silence
                pass

        with http.server.HTTPServer(("localhost", self.listen_port), Handler) as server:
            while "code" not in result:
                server.handle_request()
        if result.get("state") != expected_state:
            sys.exit("state mismatch — przerwano")
        return result["code"]

    # ---------------- API ----------------
    def get(self, path: str, name: str, *, _hops: int = 0) -> tuple[int, Any]:
        url = path if path.startswith("http") else API_BASE + path
        started = time.time()
        status, headers, payload = self._request(
            "GET", url, None, bearer=str(self.tokens.get("access_token", ""))
        )
        self._log(name, url, status, headers, started)
        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return status, {"_raw": payload[:2000]}
        # 410 GONE with a documented replacement (docs/01 §8: the API moves) → follow it once,
        # keep the evidence in the report so docs/01 can be corrected.
        replacement = (
            (body.get("extendedPayload") or {}).get("replacement")
            if isinstance(body, dict)
            else None
        )
        if status == 410 and replacement and _hops < 2:
            new_path = replacement.split(" ", 1)[-1]
            self.report.setdefault("deprecations", []).append(
                {"from": url, "to": new_path, "body": body}
            )
            print(f"  ! {url} → 410 GONE, following replacement {new_path}")
            return self.get(
                API_HOST + new_path if new_path.startswith("/") else new_path, name, _hops=_hops + 1
            )
        return status, body

    def capture_all(self, probe_limit: int) -> None:
        status, installations = self.get(
            "/equipment/installations?includeGateways=true", "installations"
        )
        collect_installation_ids(installations, self.mapping)
        self._write("installations", installations, status)
        if status != 200:
            print("installations failed:", status, installations)
            return
        devices: list[tuple[str, str, str, str]] = []
        for inst in installations.get("data", []):
            for gw in inst.get("gateways", []):
                for dev in gw.get("devices", []):
                    devices.append(
                        (
                            str(inst["id"]),
                            gw["serial"],
                            dev["id"],
                            dev.get("modelId") or dev.get("deviceType") or "unknown",
                        )
                    )
        print(f"{len(devices)} urządzeń")
        for inst_id, serial, dev_id, model in devices:
            path = f"/features/installations/{inst_id}/gateways/{serial}/devices/{dev_id}/features"
            status, features = self.get(path, f"features_{model}_{dev_id}")
            self._write(
                f"features_{model}_{dev_id}",
                features,
                status,
                extra={"deviceId": dev_id, "model": model},
            )
            time.sleep(1)
        if devices:
            inst_id, serial, dev_id, model = devices[0]
            status, gw_features = self.get(
                f"/features/installations/{inst_id}/gateways/{serial}/features", "gateway_features"
            )
            self._write("gateway_features", gw_features, status)
            status, missing = self.get(
                f"/features/installations/{inst_id}/gateways/{serial}/devices/{dev_id}/features/does.not.exist",
                "missing_feature",
            )
            self._write("error_missing_feature", missing, status)
        for i in range(probe_limit):
            inst_id, serial, dev_id, model = devices[0]
            status, body = self.get(
                f"/features/installations/{inst_id}/gateways/{serial}/devices/{dev_id}/features",
                f"probe_{i}",
            )
            if status == 429 or status >= 400:
                self._write("error_rate_limit", body, status)
                print("limit hit at probe", i, "status", status)
                break

    def probe_invalid_token(self) -> None:
        saved = self.tokens.get("access_token")
        self.tokens["access_token"] = "invalid"  # noqa: S105 — deliberately bogus
        status, body = self.get("/equipment/installations", "invalid_token")
        self._write("error_invalid_token", body, status)
        self.tokens["access_token"] = saved

    # ---------------- plumbing ----------------
    def _request(
        self, method: str, url: str, body: bytes | None, *, form: bool = False, bearer: str = ""
    ) -> tuple[int, dict[str, str], str]:
        req = urllib.request.Request(url, data=body, method=method)  # noqa: S310
        if form:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if bearer:
            req.add_header("Authorization", f"Bearer {bearer}")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed https URLs
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def _log(
        self,
        name: str,
        url: str,
        status: int,
        headers: dict[str, str],
        started: float,
        *,
        redact: bool = False,
    ) -> None:
        interesting = {
            k: v
            for k, v in headers.items()
            if k.lower().startswith(
                ("x-rate", "ratelimit", "retry-after", "x-request", "content-type")
            )
        }
        self.calls.append(
            {
                "name": name,
                "url": url if not redact else url.split("?")[0],
                "status": status,
                "ms": int((time.time() - started) * 1000),
                "headers": interesting,
            }
        )

    def _write(
        self, name: str, payload: object, status: int, extra: dict[str, str] | None = None
    ) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        anonymised = anonymise(payload, self.mapping)
        doc = {
            "_meta": {
                "status": status,
                "captured_at": datetime.now(UTC).isoformat(),
                "label": self.label,
                **(extra or {}),
            },
            "body": anonymised,
        }
        target = self.out / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json"
        target.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  ->", target.name, status)

    def finish(self) -> None:
        self.report["anonymised_ids"] = len(self.mapping)
        (self.out / "capture_report.json").write_text(
            json.dumps(anonymise(self.report, self.mapping), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.out / ".gitignore").write_text(
            "# real → placeholder mapping stays local\nserial_mapping.json\n", encoding="utf-8"
        )
        (self.out / "serial_mapping.json").write_text(
            json.dumps(self.mapping, indent=2), encoding="utf-8"
        )
        print("\nRaport:", self.out / "capture_report.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--client-id", default="")
    parser.add_argument("--out", default="backend/tests/fixtures/viessmann")
    parser.add_argument("--label", default="client-1")
    parser.add_argument("--probe-limit", type=int, default=0)
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument(
        "--sanitize-only",
        action="store_true",
        help="nie wołaj API; tylko ponownie zanonimizuj pliki w --out (idempotentne)",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help="dokładnie taki URI, jaki jest wpisany w portalu Viessmann (http://localhost:<port>/...)",
    )
    args = parser.parse_args()

    if args.sanitize_only:
        sanitize_directory(Path(args.out))
        return
    if not args.client_id:
        sys.exit("--client-id jest wymagane (poza --sanitize-only)")
    cap = Capture(args.client_id, Path(args.out), args.label, args.redirect_uri)
    cap.authorize()
    cap.capture_all(args.probe_limit)
    cap.probe_invalid_token()
    if not args.skip_refresh:
        cap.refresh()
    cap.finish()


if __name__ == "__main__":
    main()
