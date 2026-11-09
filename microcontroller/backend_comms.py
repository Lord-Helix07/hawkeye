
#Handles the communication betweeen the drone and the AWS backend
#does mission commands,
#transmit telemetry
#synchronize the mission status with the AWS backend

import threading
import time
from decimal import Decimal

import boto3
from botocore.config import Config

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_CONFIRMED = "confirmed"
STATUS_LAUNCHED = "launched"
STATUS_FAILED = "failed"
# How long to wait for the operator after ready is reported.
CONFIRM_TIMEOUT = 120
STATUS_POLL_SECONDS = 1


# One HTTP call. This is not an overall scan deadline.
_CONNECT_TIMEOUT = 2
_READ_TIMEOUT = 3

# Fields the dashboard reads from one dashboard snapshot.
_DASHBOARD_NUMBERS = (
    "latitude",
    "longitude",
    "altitude_m",
    "speed_mps",
    "heading_deg",
    "battery_pct",
)
# Live drone row. Availability stays with the account that assigned the drone.
_DRONE_LIVE = ("latitude", "longitude", "battery_pct")


#open the mission, drone, and telemetry tables for access
def open_tables():
    """Missions, Drones, and Telemetry in us-east-1. Credentials come from the machine."""
    dynamodb = boto3.resource(
        "dynamodb",
        region_name="us-east-1",
        config=Config(
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
            retries={"max_attempts": 1},
        ),
    )
    return (
        dynamodb.Table("Missions"),
        dynamodb.Table("Drones"),
        dynamodb.Table("Telemetry"),
    )

#see what the status change is --> launch or land
def requested_action(item):
    """launch or land when this mission status is a request. Otherwise None."""
    status = None if not isinstance(item, dict) else item.get("status")
    if status == "launch_requested":
        return "launch"
    if status == "land_requested":
        return "land"
    return None

#report the status of the mission --> error
def report_status(table, item_id, status):
    try:
        table.update_item(
            Key={"mission_id": item_id},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status},
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
    result["report_seq"] = seq
    result["report_state"] = "queued"


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value != value:
        return None
    if value in (float("inf"), float("-inf")):
        return None
    return value


def _dynamo_value(value):
    if isinstance(value, float):
        return Decimal(str(value))
    return value

#dashboard snapshot of what it shud look like, return a sample ()
def dashboard_snapshot(drone_id, mission_id, reading, timestamp=None):
    if timestamp is None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sample = {
        "drone_id": drone_id,
        "timestamp": timestamp,
    }
    if mission_id:
        sample["mission_id"] = mission_id
    if not isinstance(reading, dict):
        reading = {}
    #adds the lat/long, altitude, speed, heading, and battery percentage to sample
    for name in _DASHBOARD_NUMBERS:
        number = _finite_number(reading.get(name))
        if number is not None:
            sample[name] = number
    if "stale" in reading:
        sample["stale"] = bool(reading.get("stale"))
    return sample

#updates the drone's live position and battery
def _update_drone(table, item):
    fields = [name for name in _DRONE_LIVE if name in item]
    if not fields or not item.get("drone_id"):
        return
    names = {}
    values = {}
    parts = []
    for name in fields:
        names["#" + name] = name
        values[":" + name] = _dynamo_value(item[name])
        parts.append(f"#{name} = :{name}")
    table.update_item(
        Key={"drone_id": item["drone_id"]},
        UpdateExpression="SET " + ", ".join(parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def report_dashboard(telemetry_table, drones_table, sample):
    if telemetry_table is None:
        return "telemetry table is not open"
    try:
        item = {key: _dynamo_value(value) for key, value in sample.items()}
        #put the item in the telemetry table
        telemetry_table.put_item(Item=item)
        #update the drone's live position and battery
        if drones_table is not None:
            _update_drone(drones_table, item)
    except Exception as error:
        return str(error)
    return None


def confirmation_from_status(item):
    #if the item is not found, return cancelled
    if not item:
        return "cancelled"
    #get the status of the item if it exists
    status = item.get("status")
    #if the status is confirmed, return confirmed
    if status == STATUS_CONFIRMED:
        return "confirmed"
    #if the status is ready, return waiting
    if status == STATUS_READY:
        return "waiting"
    return "cancelled"

#constantly works and completes the job given to it, is mostly on wait unless a job is given to it (run starts when it flig)
class _BackendWorker:

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = []
        self.results = []
        self.wake = threading.Event()
        self.idle_event = threading.Event()
        self.idle_event.set()
        self.stop_event = threading.Event()
        self.thread = None
        self.missions = None
        self.drones = None
        self.telemetry = None
        self.inflight = None
        self._next_id = 0

    def new_id(self):
        with self.lock:
            self._next_id += 1
            return self._next_id

    def _keep_tables(self, missions, drones, telemetry):
        self.missions = missions
        self.drones = drones
        if telemetry is not None:
            self.telemetry = telemetry

    def ensure(self, missions, drones, telemetry=None):
        """Point the worker at these tables and start the thread."""
        with self.lock:
            self._keep_tables(missions, drones, telemetry)
            alive = self.thread is not None and self.thread.is_alive()
            stopping = self.stop_event.is_set()
        if alive and not stopping:
            return
        if self.thread is not None and self.thread.is_alive():
            with self.lock:
                if telemetry is None:
                    telemetry = self.telemetry
            self.stop()
        with self.lock:
            self._keep_tables(missions, drones, telemetry)
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name="hawkeye-backend")
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(_CONNECT_TIMEOUT + _READ_TIMEOUT)
        with self.lock:
            leftovers = []
            inflight = self.inflight
            if thread is not None and thread.is_alive() and isinstance(inflight, dict):
                report = str(inflight.get("kind", "")).endswith("report")
                leftovers.append(self._copy(
                    inflight,
                    "uncertain" if report else "failed",
                    reason="shutdown during send" if report else "unsent",
                ))
            for job in self.jobs:
                leftovers.append(self._copy(job, "failed", reason="unsent"))
            self.jobs = []
            self.thread = None
            self.telemetry = None
            leftovers.extend(self.results)
            self.results = []
        return leftovers

    def busy(self):
        with self.lock:
            return bool(self.inflight or self.jobs)

    def wait_idle(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if not self.busy():
                return True
            self.idle_event.wait(0.02)
        return not self.busy()

    def poll_results(self):
        with self.lock:
            found = self.results
            self.results = []
        self.wake.set()
        return found

    # Job: read this drone's mission row.
    # The row status is launch_requested, land_requested, ready, or confirmed.
    # A second check waits until the one already queued or running finishes.
    def enqueue_status_check(self, drone_id, request_id):
        with self.lock:
            pending = (
                (self.inflight and self.inflight.get("kind") == "status_check")
                or any(job.get("kind") == "status_check" for job in self.jobs)
            )
            if pending:
                return False
            self.jobs.append({
                "kind": "status_check",
                "drone_id": drone_id,
                "request_id": request_id,
            })
        self._nudge()
        return True

    # Job: write status on this mission. Launch and landing both use this write.
    def enqueue_status_report(self, mission_id, status, request_id):
        self._enqueue({
            "kind": "status_report",
            "mission_id": mission_id,
            "status": status,
            "request_id": request_id,
            "seq": request_id,
        })
        return request_id

    # Job: write the dashboard snapshot. A newer snapshot replaces one still queued.
    def enqueue_dashboard_report(self, drone_id, mission_id, reading, request_id):
        sample = dashboard_snapshot(drone_id, mission_id, reading)
        measured = any(name in sample for name in _DASHBOARD_NUMBERS)
        with self.lock:
            if self.telemetry is None or not measured:
                return None
            self.jobs = [
                job for job in self.jobs if job.get("kind") != "dashboard_report"
            ]
            self.jobs.append({
                "kind": "dashboard_report",
                "drone_id": drone_id,
                "mission_id": mission_id,
                "request_id": request_id,
                "seq": request_id,
                "sample": sample,
            })
        self._nudge()
        return request_id

    def _enqueue(self, job):
        with self.lock:
            self.jobs.append(job)
        self._nudge()

    def _nudge(self):
        self.idle_event.clear()
        self.wake.set()

    def _loop(self):
        while True:
            with self.lock:
                stopping = self.stop_event.is_set()
                job = self.jobs.pop(0) if self.jobs else None
                if job is None and stopping:
                    break
                if job is not None:
                    self.inflight = job
            if job is None:
                self.idle_event.set()
                self.wake.wait(0.05)
                self.wake.clear()
                continue
            self.idle_event.clear()
            try:
                self._execute(job)
            finally:
                with self.lock:
                    self.inflight = None
        self.idle_event.set()

    def _execute(self, job):
        with self.lock:
            missions = self.missions
            drones = self.drones
            telemetry = self.telemetry
        kind = job["kind"]
        try:
            # status_check scans until this drone's row is found, or the table ends.
            if kind == "status_check":
                item = None
                start_key = None
                while True:
                    kwargs = {
                        "FilterExpression": (
                            "drone_id = :drone_id AND ("
                            "#status = :launch_requested OR #status = :land_requested OR "
                            "#status = :ready OR #status = :confirmed)"
                        ),
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":drone_id": job["drone_id"],
                            ":launch_requested": "launch_requested",
                            ":land_requested": "land_requested",
                            ":ready": STATUS_READY,
                            ":confirmed": STATUS_CONFIRMED,
                        },
                    }
                    if start_key is not None:
                        kwargs["ExclusiveStartKey"] = start_key
                    response = missions.scan(**kwargs)
                    found = response.get("Items", [])
                    if found:
                        item = found[0]
                        break
                    start_key = response.get("LastEvaluatedKey")
                    if not start_key:
                        break
                self._post(self._copy(job, "completed", item=item))
                return
            if kind == "dashboard_report":
                error = report_dashboard(telemetry, drones, job.get("sample") or {})
            else:
                # status_report sets the mission status. A network error stays uncertain.
                error = report_status(missions, job["mission_id"], job["status"])
        except Exception as error:
            self._post(self._copy(job, "uncertain", error=str(error)))
            return
        if error:
            self._post(self._copy(job, "uncertain", error=error))
        else:
            self._post(self._copy(job, "completed"))

    def _copy(self, job, state, **extra):
        result = {
            "kind": job.get("kind"),
            "request_id": job.get("request_id"),
            "mission_id": job.get("mission_id"),
            "drone_id": job.get("drone_id"),
            "seq": job.get("seq"),
            "state": state,
        }
        result.update(extra)
        return result

    def _post(self, result):
        with self.lock:
            self.results.append(result)
        self.wake.set()


_worker = _BackendWorker()


# Start the shared worker, or point the running one at these tables.
def ensure_worker(missions, drones, telemetry=None):
    _worker.ensure(missions, drones, telemetry)


# Stop the shared worker and return jobs that never got a result.
def stop_worker():
    return _worker.stop()


# Next request id. Callers store it so they can match the result later.
def new_request_id():
    return _worker.new_id()


# True while the shared worker still has a job.
def worker_busy():
    return _worker.busy()


# Wait until the shared worker has nothing left to send.
def wait_idle(timeout):
    return _worker.wait_idle(timeout)


# Take the results the shared worker has finished.
def poll_results():
    return _worker.poll_results()


# Ask the shared worker to read this drone's mission status.
def enqueue_status_check(drone_id, request_id):
    return _worker.enqueue_status_check(drone_id, request_id)


# Ask the shared worker to write this mission's status.
def enqueue_status_report(mission_id, status, request_id):
    return _worker.enqueue_status_report(mission_id, status, request_id)


# Send the dashboard snapshot for this drone.
# None means the Telemetry table is not open, or the snapshot has no measurement.
def enqueue_dashboard(drone_id, mission_id, reading, request_id):
    return _worker.enqueue_dashboard_report(drone_id, mission_id, reading, request_id)


def dashboard_open():
    """True after open_tables has handed the worker a Telemetry table."""
    with _worker.lock:
        return _worker.telemetry is not None
