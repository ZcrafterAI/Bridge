"""A pretend mainframe for `zcrafter-bridge --demo`.

It answers the z/OSMF REST calls Bridge makes, from a few datasets, z/OS UNIX files and jobs
held in memory, so anyone can try Bridge with no mainframe. It listens on this machine only
and is gone when the server stops. It is a stage set, not an emulator: enough for every tool
to return something sensible.

The story it sets up: job PAYRUN abended with S0C7 because PAYCALC does arithmetic on a
blank field. Guard the field, submit PAYRUN again, and it ends CC 0000.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

USER = "IBMUSER"

_PAYCALC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYCALC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-HOURS        PIC 9(3)V99.
       01  WS-RATE         PIC 9(3)V99 VALUE 25.00.
       01  WS-PAY          PIC 9(7)V99.
       PROCEDURE DIVISION.
           MOVE TC-HOURS TO WS-HOURS.
           COMPUTE WS-PAY = WS-HOURS * WS-RATE.
           DISPLAY 'PAY ' WS-PAY.
           GOBACK.
"""

_PAYRUN = """\
//PAYRUN   JOB (ACCT),'PAYROLL',CLASS=A,MSGCLASS=X
//CALC     EXEC PGM=PAYCALC
//STEPLIB  DD DSN=IBMUSER.DEMO.LOAD,DISP=SHR
//TIMECARD DD DSN=IBMUSER.DEMO.TIMECARD,DISP=SHR
//SYSOUT   DD SYSOUT=*
"""


def _seed() -> dict[str, Any]:
    return {
        "datasets": {
            "IBMUSER.DEMO.COBOL": {"PAYCALC": _PAYCALC, "HELLO": "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n       PROCEDURE DIVISION.\n           DISPLAY 'HELLO FROM THE DEMO MAINFRAME'.\n           GOBACK.\n"},
            "IBMUSER.DEMO.JCL": {"PAYRUN": _PAYRUN},
            "IBMUSER.DEMO.TIMECARD": "000123 04000\n000124      \n000125 03750\n",
            "IBMUSER.PROD.PAYROLL": {"MASTER": "PRODUCTION DATA. DO NOT CHANGE.\n"},
        },
        "uss": {
            "/u/ibmuser/payroll.log": "02:00:01 PAYRUN started\n02:00:02 ERROR S0C7 in step CALC\n02:00:02 PAYRUN ended\n",
            "/u/ibmuser/notes.txt": "Timecards arrive at 01:30. PAYRUN runs at 02:00.\n",
        },
        "jobs": [_job("PAYRUN", "JOB00042", "ABEND S0C7")],
        "next_job": 43,
    }


def _job(name: str, job_id: str, retcode: str) -> dict[str, Any]:
    bad = retcode != "CC 0000"
    log = [
        f"02.00.01 {job_id}  $HASP373 {name} STARTED - INIT 1 - CLASS A",
        f"02.00.02 {job_id}  IEA995I SYMPTOM DUMP OUTPUT  SYSTEM COMPLETION CODE=0C7" if bad
        else f"02.00.02 {job_id}  IEF142I {name} CALC - STEP WAS EXECUTED - COND CODE 0000",
        f"02.00.02 {job_id}  $HASP395 {name} ENDED" + (" - ABEND=S0C7" if bad else " - RC=0000"),
    ]
    return {
        "jobname": name, "jobid": job_id, "owner": USER, "status": "OUTPUT", "retcode": retcode,
        "class": "A", "type": "JOB",
        "steps": [{"step-number": 1, "step-name": "CALC", "program-name": "PAYCALC",
                   "completion": "ABEND S0C7" if bad else "CC 0000"}],
        "spool": [("JESMSGLG", "\n".join(log) + "\n"), ("JESJCL", _PAYRUN),
                  ("SYSOUT", "" if bad else "PAY 0100000\nPAY 0000000\nPAY 0093750\n")],
    }


def _matches(pattern: str, name: str) -> bool:
    text = pattern.strip().upper().strip("'")
    regex = "".join(".*" if part == "**" else "[^.]*" if part == "*" else re.escape(part)
                    for part in re.split(r"(\*\*|\*)", text))
    return re.fullmatch(regex, name) is not None or name.startswith(text.rstrip("*.") + ".") or name == text


class _Handler(http.server.BaseHTTPRequestHandler):
    state: dict[str, Any] = {}

    def log_message(self, *args: Any) -> None:
        return

    # ---- plumbing ----
    def _send(self, code: int, body: Any = b"", content_type: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _missing(self, what: str) -> None:
        self._send(404, {"category": 4, "rc": 8, "reason": 0, "message": f"{what} not found"})

    def _body(self) -> str:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")

    def _where(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        return path[path.index("/zosmf") + len("/zosmf"):] if "/zosmf" in path else path, parse_qs(parsed.query)

    def _dataset(self, path: str) -> tuple[str, str | None] | None:
        match = re.fullmatch(
            r"/restfiles/ds/(?:-\([^)]*\)/)?([A-Z0-9.$#@]+)(?:\(([A-Z0-9$#@]+)\))?", path, re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).upper(), match.group(2).upper() if match.group(2) else None

    def _find_job(self, path: str) -> dict[str, Any] | None:
        match = re.match(r"/restjobs/jobs/([A-Z0-9$#@]+)/([A-Z0-9]+)", path, re.IGNORECASE)
        if not match:
            return None
        return next((j for j in self.state["jobs"] if j["jobid"] == match.group(2).upper()), None)

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in job.items() if k not in ("steps", "spool")}

    # ---- GET ----
    def do_GET(self) -> None:
        path, query = self._where()
        state = self.state
        if path == "/info":
            return self._send(200, {"zosmf_hostname": "demo.zcrafter.test", "zos_version": "04.29.00",
                                    "zosmf_version": "29", "api_version": "1"})
        if path == "/resttopology/systems":
            return self._send(200, {"items": [{"systemNickName": "DEMO", "systemName": "DEMO",
                                               "sysplexName": "DEMOPLEX", "zosVR": "z/OS V3R1"}], "numRows": 1})
        if path == "/restfiles/ds":
            pattern = (query.get("dslevel") or ["**"])[0]
            items = [{"dsname": name, "dsorg": "PO" if isinstance(value, dict) else "PS", "recfm": "FB",
                      "lrecl": "80", "vol": "DEMO01"}
                     for name, value in sorted(state["datasets"].items()) if _matches(pattern, name)]
            return self._send(200, {"items": items, "returnedRows": len(items), "JSONversion": 1})
        if path.lower().endswith("/member") and path.startswith("/restfiles/ds/"):
            name = path[len("/restfiles/ds/"):-len("/member")].upper()
            value = state["datasets"].get(name)
            if not isinstance(value, dict):
                return self._missing(name)
            items = [{"member": member} for member in sorted(value)]
            return self._send(200, {"items": items, "returnedRows": len(items), "JSONversion": 1})
        target = self._dataset(path)
        if target:
            name, member = target
            value = state["datasets"].get(name)
            text = value.get(member) if isinstance(value, dict) and member else value if isinstance(value, str) else None
            return self._send(200, text, "text/plain") if isinstance(text, str) else self._missing(name)
        if path == "/restfiles/fs":
            folder = (query.get("path") or ["/"])[0].rstrip("/") + "/"
            names = sorted({key[len(folder):].split("/")[0] for key in state["uss"] if key.startswith(folder)})
            items = [{"name": n, "mode": "-rw-r--r--" if folder + n in state["uss"] else "drwxr-xr-x",
                      "size": len(state["uss"].get(folder + n, "")), "user": USER, "group": "SYS1"} for n in names]
            return self._send(200, {"items": items, "returnedRows": len(items), "totalRows": len(items)})
        if path.startswith("/restfiles/fs/"):
            file = path[len("/restfiles/fs"):]
            return self._send(200, state["uss"][file], "text/plain") if file in state["uss"] else self._missing(file)
        if path.rstrip("/") == "/restjobs/jobs":
            wanted = (query.get("jobid") or [""])[0].upper()
            prefix = (query.get("prefix") or ["*"])[0].upper().rstrip("*")
            jobs = [self._public(j) for j in state["jobs"]
                    if (not wanted or j["jobid"] == wanted) and j["jobname"].startswith(prefix)]
            return self._send(200, jobs)
        job = self._find_job(path)
        if job:
            files = [{"id": i + 101, "ddname": dd, "stepname": "JES2" if dd.startswith("JES") else "CALC",
                      "jobid": job["jobid"], "jobname": job["jobname"], "byte-count": len(text)}
                     for i, (dd, text) in enumerate(job["spool"])]
            if path.endswith("/files"):
                return self._send(200, files)
            record = re.search(r"/files/(\d+)/records$", path)
            if record:
                index = int(record.group(1)) - 101
                if 0 <= index < len(job["spool"]):
                    return self._send(200, job["spool"][index][1], "text/plain")
                return self._missing("spool file")
            body = self._public(job)
            if (query.get("step-data") or [""])[0].upper() == "Y":
                body["step-data"] = job["steps"]
            return self._send(200, body)
        self._missing(path)

    # ---- PUT ----
    def do_PUT(self) -> None:
        path, _ = self._where()
        state = self.state
        body = self._body()
        if path == "/tsoApp/v1/tso":
            command = json.loads(body).get("tsoCmd", "")
            lines = sorted(state["datasets"]) if command.upper().startswith(("LISTC", "LISTDS")) else [f"{command.split()[0].upper()} COMPLETED"]
            return self._send(200, {"cmdResponse": [{"message": line} for line in [*lines, "READY"]]})
        if path.startswith("/restconsoles/consoles/"):
            return self._send(200, {"cmd-response": "IEE114I 02.00.00 ACTIVITY\r JOBS     M/S    TS USERS\r 00001    00012  00001"})
        if path.rstrip("/") == "/restjobs/jobs":
            jcl = body
            if body.lstrip().startswith("{"):
                target = self._dataset("/restfiles/ds/" + json.loads(body).get("file", "").strip("/' "))
                value = state["datasets"].get(target[0]) if target else None
                jcl = value.get(target[1], "") if isinstance(value, dict) and target and target[1] else ""
                if not jcl:
                    return self._missing("JCL")
            card = re.match(r"//(\S+)\s+JOB\b", jcl)
            if not card:
                return self._send(400, {"category": 6, "rc": 4, "message": "No job card found in the JCL"})
            # PAYCALC abends until the hours field is checked before the arithmetic.
            program = state["datasets"]["IBMUSER.DEMO.COBOL"].get("PAYCALC", "")
            fixed = "PGM=PAYCALC" not in jcl.upper() or "NUMERIC" in program.upper()
            job = _job(card.group(1).upper(), f"JOB{state['next_job']:05d}", "CC 0000" if fixed else "ABEND S0C7")
            state["next_job"] += 1
            state["jobs"].append(job)
            return self._send(201, self._public(job))
        job = self._find_job(path)
        if job:
            request = json.loads(body or "{}")
            if request.get("class"):
                job["class"] = request["class"]
            return self._send(200, {"jobid": job["jobid"], "jobname": job["jobname"], "status": 0,
                                    "message": f"Request was successful ({request.get('request', 'update')})."})
        if path.startswith("/restfiles/fs/"):
            file = path[len("/restfiles/fs"):]
            if body.lstrip().startswith("{") and "request" in body:
                request = json.loads(body)
                if request.get("request") == "move" and request.get("from") in state["uss"]:
                    state["uss"][file] = state["uss"].pop(request["from"])
                return self._send(200, {})
            state["uss"][file] = body
            return self._send(204)
        target = self._dataset(path)
        if target:
            name, member = target
            if body.lstrip().startswith("{") and '"request"' in body:
                request = json.loads(body)
                source = request.get("from-dataset") or {}
                origin = state["datasets"].get(str(source.get("dsn", "")).upper())
                if request.get("request") == "rename" and origin is not None and not member:
                    state["datasets"][name] = state["datasets"].pop(str(source["dsn"]).upper())
                elif request.get("request") == "rename" and isinstance(origin, dict) and member:
                    origin[member] = origin.pop(str(source.get("member", "")).upper())
                elif request.get("request") == "copy" and origin is not None:
                    if member and isinstance(origin, dict) and source.get("member"):
                        if not isinstance(state["datasets"].get(name), dict):
                            state["datasets"][name] = {}
                        state["datasets"][name][member] = origin[str(source["member"]).upper()]
                    else:
                        state["datasets"][name] = json.loads(json.dumps(origin))
                return self._send(200, {})
            if name not in state["datasets"]:
                return self._missing(name)
            if member:
                state["datasets"][name][member] = body
            else:
                state["datasets"][name] = body
            return self._send(204)
        self._missing(path)

    # ---- POST / DELETE ----
    def do_POST(self) -> None:
        path, _ = self._where()
        self._body()
        target = self._dataset(path)
        if target and not target[1]:
            self.state["datasets"].setdefault(target[0], {})
            return self._send(201)
        if path.startswith("/restfiles/fs/"):
            self.state["uss"].setdefault(path[len("/restfiles/fs"):], "")
            return self._send(201)
        self._missing(path)

    def do_DELETE(self) -> None:
        path, _ = self._where()
        state = self.state
        job = self._find_job(path)
        if job:
            state["jobs"].remove(job)
            return self._send(200, {"jobid": job["jobid"], "status": 0})
        if path.startswith("/restfiles/fs/"):
            file = path[len("/restfiles/fs"):]
            for key in [k for k in state["uss"] if k == file or k.startswith(file.rstrip("/") + "/")]:
                del state["uss"][key]
            return self._send(204)
        target = self._dataset(path)
        if target and target[0] in state["datasets"]:
            name, member = target
            if member:
                state["datasets"][name].pop(member, None)
            else:
                del state["datasets"][name]
            return self._send(204)
        self._missing(path)


def start_demo_mainframe() -> tuple[http.server.ThreadingHTTPServer, int]:
    """Start the pretend mainframe on a free local port. Returns (server, port)."""
    handler = type("DemoHandler", (_Handler,), {"state": _seed()})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
