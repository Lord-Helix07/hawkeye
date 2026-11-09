"""Backend reads and writes for the launch handshake.

This module does not read MAVLink, arm, command the aircraft, or decide
that the flight controller is ready.
"""

import os
import queue
import threading
import time

# Missions.status is the mission lifecycle. Live rows use pending, active,
# visual_contact_lost, and completed. A pending row can omit drone_id.
# launch_status is a separate handshake attribute on that same row.
# Current Missions and Drones items do not contain launch_status,
# launch_reason, launch_reasons, or landing_status.
LAUNCH_REQUESTED = "requested"
LAUNCH_READY = "ready"
LAUNCH_NOT_READY = "not_ready"
LAUNCH_CONFIRMED = "confirmed"
LAUNCH_FINISHED = "launched"
LAUNCH_FAILED_STATUS = "failed"
# How long to wait for the operator after ready is reported.
CONFIRM_TIMEOUT = 120
CONFIRM_POLL_SECONDS = 1


# One HTTP call. This is not an overall scan deadline.
_CONNECT_TIMEOUT = 2
_READ_TIMEOUT = 3


def _region_name():
    """Region from the process environment. The account tables are in us-east-1."""
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def _dynamo_resource():
    """Default credential chain. No profile name and no embedded keys.

    AWS_PROFILE, AWS_ACCESS_KEY_ID, and the other standard variables are
    read by the SDK itself. DYNAMODB_ENDPOINT_URL selects a local endpoint.
    """
    import boto3
    from botocore.config import Config

    kwargs = {
        "region_name": _region_name(),
        "config": Config(
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
            retries={"max_attempts": 1},
        ),
    }
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


# Missions is keyed by mission_id, get the missions table
def missions_table():
    return _dynamo_resource().Table("Missions")


def _launch_scan_kwargs(drone_id):
    """Fresh arguments for this drone's requested, ready, or confirmed row."""
    return {
        "FilterExpression": (
            "drone_id = :drone_id AND ("
            "launch_status = :requested OR "
            "launch_status = :ready OR "
            "launch_status = :confirmed)"
        ),
        "ExpressionAttributeValues": {
            ":drone_id": drone_id,
            ":requested": LAUNCH_REQUESTED,
            ":ready": LAUNCH_READY,
            ":confirmed": LAUNCH_CONFIRMED,
        },
    }


# Poll Missions for this drone. The website sets launch_status to requested.
# The assigned drone is stored as drone_id. Returns the mission row, or None.
def find_launch_request(table, drone_id):
    # None means start at the beginning of the table
    start_key = None
    while True:
        # Missions has no index on drone_id, so scan until this drone's launch row.
        kwargs = _launch_scan_kwargs(drone_id)

        # continue the scan from the last page, when there is one
        if start_key is not None:
            kwargs["ExclusiveStartKey"] = start_key

        response = table.scan(**kwargs)
        items = response.get("Items", [])
        # a drone has one mission, so the first launch row is the one to handle
        if items:
            return items[0]

        # missing key means this page was the last one
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break

    return None


def scan_launch_page(table, drone_id, start_key=None):
    """One Missions page. The cursor is kept by the caller so the next page is not skipped."""
    kwargs = _launch_scan_kwargs(drone_id)
    if start_key is not None:
        kwargs["ExclusiveStartKey"] = start_key
    try:
        response = table.scan(**kwargs)
    except Exception as error:
        return None, None, str(error)
    items = response.get("Items", [])
    if items:
        return items[0], None, None
    return None, response.get("LastEvaluatedKey"), None


#what is the actual launch status --> this is the function that updates the launch_status in the database
def report_launch(table, mission_id, launch_status, reason, reasons=None):
    values = {
        ":launch_status": launch_status,
        ":reason": reason,
    }
    expression = "SET launch_status = :launch_status, launch_reason = :reason"
    if reasons is None:
        expression += " REMOVE launch_reasons"
    else:
        expression += ", launch_reasons = :reasons"
        values[":reasons"] = reasons
    try:
        table.update_item(
            Key={"mission_id": mission_id},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )
    except Exception as error:
        return str(error)
    return None


#attached dynamo error to the result if it is not None
def attach_report_error(result, report_error):
    if report_error:
        result["report_error"] = report_error
    return result


def record_report_enqueue(result, seq):
    """Record whether a report was accepted onto the queue.

    This does not write to DynamoDB. A missing seq is a full queue.
    An error already stored on the result is left as it is.
    """
    result["report_seq"] = seq
    if not seq:
        result["report_state"] = "failed"
        if "report_error" not in result:
            result["report_error"] = "report queue full"
        return False
    result["report_state"] = "queued"
    return True


#this is what repeatedly checks the launch_status for the operator to confirm
def read_launch_confirmation(table, mission_id):
    """One Missions read. Does not wait and does not read the flight controller."""
    try:
        item = table.get_item(
            Key={"mission_id": mission_id},
            ConsistentRead=True,
        ).get("Item")
    except Exception:
        return "read_failed"
    if item is None:
        return "cancelled"
    launch_status = item.get("launch_status")
    if launch_status == LAUNCH_CONFIRMED:
        return "confirmed"
    if launch_status != LAUNCH_READY:
        return "cancelled"
    return "waiting"


LAND_REQUESTED = "LAND_REQUESTED"


def drones_table():
    """Drones table. Imported here so a missing backend does not import at startup."""
    return _dynamo_resource().Table("Drones")


def find_landing_request(table, drone_id):
    """Return this drone's row when landing_status is LAND_REQUESTED.

    A launch request, a fault_reason field, or any other status does not
    count. The row is not given to landing_sequence.
    """
    item = table.get_item(Key={"drone_id": drone_id}).get("Item")
    if not item or item.get("landing_status") != LAND_REQUESTED:
        return None
    return item


def report_landing(table, drone_id, status):
    """Write landing_status once. Return an error string, or None."""
    try:
        table.update_item(
            Key={"drone_id": drone_id},
            UpdateExpression="SET landing_status = :landing_status",
            ExpressionAttributeValues={":landing_status": status},
        )
    except Exception as error:
        return str(error)
    return None


def landing_progress(table, drone_id):
    """Progress callback for landing. One write. Failure stays on the result."""

    def progress(status, result):
        writer = table
        if writer is None:
            try:
                writer = drones_table()
            except Exception as error:
                if "report_error" not in result:
                    result["report_error"] = str(error)
                return
        error = report_landing(writer, drone_id, status)
        if error and "report_error" not in result:
            result["report_error"] = error

    return progress


_RESULT_LIMIT = 32
_HOLD_LIMIT = 8


class _BackendWorker:
    """Network thread. It never reads the flight controller or the flight dict."""

    def __init__(self):
        self.lock = threading.Lock()
        self.results = queue.Queue(_RESULT_LIMIT)
        self.wake = threading.Event()
        self.idle_event = threading.Event()
        self.idle_event.set()
        self.stop_event = threading.Event()
        self.thread = None
        self.missions = None
        self.drones = None
        self.session_id = 0
        self.launch_token = 0
        self.mission_id = None
        self.phase = None
        self.landing = None
        self.confirm = None
        self.launch_report = None
        self.landing_report = None
        self.scan_request = None
        self.scan_cursor = None
        self.inflight = None
        self.hold = []
        self.stuck = None
        self.pending_post = None
        self.since_other = 0
        self._next_id = 0
        self.seqs = {}
        self.report_seq = {}

    def begin_session(self):
        with self.lock:
            self.session_id += 1
            self.launch_token += 1
            self.mission_id = None
            self.phase = None
            return self.session_id

    def tokens(self):
        with self.lock:
            return self.session_id, self.launch_token

    def set_launch_context(self, mission_id, phase):
        """Advance the launch token only. The session id stays put."""
        with self.lock:
            if mission_id != self.mission_id or phase != self.phase:
                self.launch_token += 1
                self.mission_id = mission_id
                self.phase = phase
            return self.launch_token

    def new_id(self):
        with self.lock:
            self._next_id += 1
            return self._next_id

    def ensure(self, missions, drones):
        """Point the worker at these tables. A running job keeps the table it already loaded."""
        with self.lock:
            self.missions = missions
            self.drones = drones
            alive = self.thread is not None and self.thread.is_alive()
            stopping = self.stop_event.is_set()
        if alive and not stopping:
            return
        if self.thread is not None and self.thread.is_alive():
            self.stop()
        with self.lock:
            self.missions = missions
            self.drones = drones
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name="hawkeye-backend")
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(_CONNECT_TIMEOUT + _READ_TIMEOUT)
        leftovers = []
        with self.lock:
            if thread is not None and thread.is_alive() and isinstance(self.inflight, dict):
                if str(self.inflight.get("kind", "")).endswith("report"):
                    leftovers.append(self._copy(self.inflight, "uncertain", reason="shutdown during send"))
            for item in (self.launch_report, self.landing_report, self.confirm, self.landing):
                if item is not None:
                    leftovers.append(self._copy(item, "failed", reason="unsent"))
            self.launch_report = None
            self.landing_report = None
            self.confirm = None
            self.landing = None
            self.scan_request = None
            self.scan_cursor = None
            self.thread = None
        leftovers.extend(self.poll_results())
        return leftovers

    def busy(self):
        with self.lock:
            return bool(
                self.inflight
                or self.landing
                or self.confirm
                or self.launch_report
                or self.landing_report
                or self.scan_request
                or self.scan_cursor
                or self.stuck
                or self.pending_post
            )

    def wait_idle(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if not self.busy():
                return True
            self.idle_event.wait(0.02)
        return not self.busy()

    def poll_results(self):
        found = []
        while True:
            try:
                found.append(self.results.get_nowait())
            except queue.Empty:
                break
        self.wake.set()
        return found

    def enqueue_landing_check(self, drone_id, session_id, request_id):
        job = self._job("landing_check", request_id, session_id, None, drone_id=drone_id)
        with self.lock:
            if session_id != self.session_id or self.landing is not None:
                return False
            self.landing = job
        self._nudge()
        return True

    def enqueue_launch_scan(self, drone_id, session_id, launch_token, request_id):
        job = self._job(
            "launch_scan", request_id, session_id, launch_token, drone_id=drone_id, start_key=None
        )
        with self.lock:
            if session_id != self.session_id or launch_token != self.launch_token:
                return False
            if self.scan_request is not None or self.scan_cursor is not None:
                return False
            self.scan_request = job
        self._nudge()
        return True

    def enqueue_launch_confirm(self, mission_id, session_id, launch_token, request_id):
        job = self._job(
            "launch_confirm",
            request_id,
            session_id,
            launch_token,
            mission_id=mission_id,
        )
        with self.lock:
            if session_id != self.session_id or launch_token != self.launch_token:
                return False
            if self.confirm is not None:
                return False
            self.confirm = job
        self._nudge()
        return True

    def enqueue_launch_report(self, mission_id, session_id, status, reason, reasons, request_id):
        return self._enqueue_report(
            "launch_report",
            "launch",
            mission_id,
            session_id,
            request_id,
            status,
            reason,
            reasons,
            self._set_launch_report,
        )

    def enqueue_landing_report(self, drone_id, session_id, status, request_id):
        return self._enqueue_report(
            "landing_report",
            "landing",
            drone_id,
            session_id,
            request_id,
            status,
            None,
            None,
            self._set_landing_report,
        )

    def _set_launch_report(self, job):
        old = self.launch_report
        self.launch_report = job
        return old

    def _set_landing_report(self, job):
        old = self.landing_report
        self.landing_report = job
        return old

    def _enqueue_report(self, kind, seq_kind, key, session_id, request_id, status, reason, reasons, setter):
        slot = (seq_kind, key)
        with self.lock:
            if session_id != self.session_id:
                return None
            self.seqs[slot] = self.seqs.get(slot, 0) + 1
            seq = self.seqs[slot]
            self.report_seq[slot] = seq
            job = self._job(
                kind,
                request_id,
                session_id,
                None,
                mission_id=key if seq_kind == "launch" else None,
                drone_id=key if seq_kind == "landing" else None,
                status=status,
                reason=reason,
                reasons=reasons,
                seq=seq,
                key=slot,
            )
            old = setter(job)
            if old is not None and not (old.get("key") == slot and old.get("seq", 0) < seq):
                setter(old)
                self.seqs[slot] -= 1
                self.report_seq[slot] = self.seqs[slot]
                return None
        if old is not None:
            self._post(self._copy(old, "failed", reason="superseded"))
        self._nudge()
        return seq

    def _job(self, kind, request_id, session_id, launch_token, **extra):
        job = {
            "kind": kind,
            "request_id": request_id,
            "session_id": session_id,
            "launch_token": launch_token,
        }
        job.update(extra)
        return job

    def _nudge(self):
        self.idle_event.clear()
        self.wake.set()

    def _loop(self):
        while True:
            self._flush()
            with self.lock:
                blocked = self.pending_post is not None
                stopping = self.stop_event.is_set()
                reports_left = self.launch_report is not None or self.landing_report is not None
            if blocked:
                self.wake.wait(0.05)
                self.wake.clear()
                continue
            if stopping and not reports_left:
                break
            job = self._pick(stopping)
            if job is None:
                self.idle_event.set()
                if stopping:
                    break
                self.wake.wait(0.05)
                self.wake.clear()
                continue
            self.idle_event.clear()
            with self.lock:
                self.inflight = job
            try:
                self._execute(job)
            finally:
                with self.lock:
                    self.inflight = None
        self.idle_event.set()

    def _pick(self, stopping):
        with self.lock:
            if stopping:
                return self._take_report()
            has_other = any((
                self.confirm is not None,
                self.launch_report is not None,
                self.landing_report is not None,
                self.scan_cursor is not None,
                self.scan_request is not None,
            ))
            if self.landing is not None and not (has_other and self.since_other >= 1):
                self.since_other += 1
                item = self.landing
                self.landing = None
                return item
            if self.confirm is not None:
                self.since_other = 0
                item = self.confirm
                self.confirm = None
                return item
            report = self._take_report()
            if report is not None:
                self.since_other = 0
                return report
            if self.scan_cursor is not None:
                self.since_other = 0
                item = self.scan_cursor
                self.scan_cursor = None
                return item
            if self.scan_request is not None:
                self.since_other = 0
                item = self.scan_request
                self.scan_request = None
                return item
            if self.landing is not None:
                self.since_other += 1
                item = self.landing
                self.landing = None
                return item
            return None

    def _take_report(self):
        if self.launch_report is not None:
            item = self.launch_report
            self.launch_report = None
            return item
        if self.landing_report is not None:
            item = self.landing_report
            self.landing_report = None
            return item
        return None

    def _valid(self, job):
        if job.get("session_id") != self.session_id:
            return False
        if job["kind"] == "landing_check":
            return True
        if job["kind"] in ("launch_report", "landing_report"):
            return job.get("seq") == self.report_seq.get(job.get("key"))
        return job.get("launch_token") == self.launch_token

    def _execute(self, job):
        with self.lock:
            allowed = self._valid(job)
            missions = self.missions
            drones = self.drones
        if not allowed:
            self._post(self._copy(job, "failed", reason="superseded"))
            return
        kind = job["kind"]
        if kind == "launch_scan":
            self._scan(job, missions)
            return
        if kind == "launch_confirm":
            outcome = read_launch_confirmation(missions, job["mission_id"])
            self._post(self._copy(job, "completed", outcome=outcome))
            return
        if kind == "landing_check":
            try:
                item = find_landing_request(drones, job["drone_id"])
            except Exception as error:
                self._post(self._copy(job, "uncertain", error=str(error)))
                return
            self._post(self._copy(job, "completed", requested=item is not None))
            return
        if kind == "launch_report":
            error = report_launch(
                missions, job["mission_id"], job["status"], job["reason"], job.get("reasons")
            )
        else:
            error = report_landing(drones, job["drone_id"], job["status"])
        if error:
            self._post(self._copy(job, "uncertain", error=error))
        else:
            self._post(self._copy(job, "completed"))

    def _scan(self, job, table):
        item, nxt, error = scan_launch_page(table, job["drone_id"], job.get("start_key"))
        if error:
            self._post(self._copy(job, "uncertain", error=error))
            return
        if item is not None or not nxt:
            self._post(self._copy(job, "completed", item=item))
            return
        continued = dict(job)
        continued["start_key"] = nxt
        with self.lock:
            if not self._valid(continued):
                stale = True
            else:
                self.scan_cursor = continued
                stale = False
        if stale:
            self._post(self._copy(job, "failed", reason="superseded"))

    def _copy(self, job, state, **extra):
        result = {
            "kind": job.get("kind"),
            "request_id": job.get("request_id"),
            "session_id": job.get("session_id"),
            "launch_token": job.get("launch_token"),
            "mission_id": job.get("mission_id"),
            "drone_id": job.get("drone_id"),
            "seq": job.get("seq"),
            "key": job.get("key"),
            "state": state,
        }
        result.update(extra)
        return result

    def _post(self, result):
        with self.lock:
            self.pending_post = result
        self._flush()

    def _flush(self):
        while True:
            with self.lock:
                item = None
                if self.stuck is not None:
                    item = self.stuck
                    self.stuck = None
                elif self.hold:
                    item = self.hold.pop(0)
                elif self.pending_post is not None:
                    item = self.pending_post
                    self.pending_post = None
            if item is None:
                return
            try:
                self.results.put_nowait(item)
            except queue.Full:
                with self.lock:
                    kind = item.get("kind")
                    if kind in ("launch_scan", "launch_confirm") and len(self.hold) < _HOLD_LIMIT:
                        self.hold.append(item)
                    elif self.stuck is None:
                        self.stuck = item
                    else:
                        self.pending_post = item
                return


_worker = _BackendWorker()


def begin_session():
    return _worker.begin_session()


def ensure_worker(missions, drones):
    _worker.ensure(missions, drones)


def stop_worker():
    return _worker.stop()


def current_tokens():
    return _worker.tokens()


def set_launch_context(mission_id, phase):
    return _worker.set_launch_context(mission_id, phase)


def new_request_id():
    return _worker.new_id()


def worker_busy():
    return _worker.busy()


def wait_idle(timeout):
    return _worker.wait_idle(timeout)


def poll_results():
    return _worker.poll_results()


def enqueue_landing_check(drone_id, session_id, request_id):
    return _worker.enqueue_landing_check(drone_id, session_id, request_id)


def enqueue_launch_scan(drone_id, session_id, launch_token, request_id):
    return _worker.enqueue_launch_scan(drone_id, session_id, launch_token, request_id)


def enqueue_launch_confirm(mission_id, session_id, launch_token, request_id):
    return _worker.enqueue_launch_confirm(mission_id, session_id, launch_token, request_id)


def enqueue_launch_report(mission_id, session_id, status, reason, reasons, request_id):
    return _worker.enqueue_launch_report(
        mission_id, session_id, status, reason, reasons, request_id
    )


def enqueue_landing_report(drone_id, session_id, status, request_id):
    return _worker.enqueue_landing_report(drone_id, session_id, status, request_id)
