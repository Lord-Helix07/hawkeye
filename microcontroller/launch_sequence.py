#Assigned to Alvina
#handles launch sequence for the drone
#1. read Missions.launch_status for this drone
#2. check comms and readiness (heartbeat, GPS, pre-arm)
#3. report ready or not ready on launch_status
#4. wait for the operator to set launch_status to confirmed
#5. LAUNCH only after that confirmation
#6. confirm the climb from relative altitude
#7. hand off to autonomous mode
#8. return the status of the launch

import time

from pymavlink import mavutil

TARGET_ALTITUDE = 9.144  # meters relative to home (30 feet)
ALTITUDE_TOLERANCE = 0.5
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
ALTITUDE_TIMEOUT = 45
PROGRESS_TIMEOUT = 12
MIN_PROGRESS = 0.25
READINESS_TIMEOUT = 15
# Seconds. A heartbeat or position older than this is not current.
FRESH_SECONDS = 5
FC_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200

# Missions.status stays the mission lifecycle: active, visual_contact_lost, completed.
# launch_status is the launch handshake on that same row.
LAUNCH_REQUESTED = "requested"
LAUNCH_READY = "ready"
LAUNCH_NOT_READY = "not_ready"
LAUNCH_CONFIRMED = "confirmed"
LAUNCH_FINISHED = "launched"
LAUNCH_FAILED_STATUS = "failed"
# How long to wait for the operator after ready is reported.
CONFIRM_TIMEOUT = 120
CONFIRM_POLL_SECONDS = 1
ARM = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
PREARM = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
ARMED = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED

# Missions is keyed by mission_id, get the missions table
def missions_table():
    import boto3
    return boto3.resource("dynamodb").Table("Missions")

# Poll Missions for this drone. The website sets launch_status to requested.
# The assigned drone is stored as drone_id. Returns the mission row, or None.
def find_launch_request(table, drone_id):
    # None means start at the beginning of the table
    start_key = None
    while True:
        # Missions has no index on drone_id, so scan until this drone's launch row.
        kwargs = {
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
def _with_report(result, report_error):
    if report_error:
        result["report_error"] = report_error
    return result



#this is what repeatedly checks the launch_status for the operator to confirm
def wait_for_confirmation(table, link, mission_id, timeout=CONFIRM_TIMEOUT):
    deadline = time.monotonic() + timeout
    last_heartbeat = time.monotonic()
    next_poll = time.monotonic()
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        message = link.recv_match(
            type="HEARTBEAT", blocking=True, timeout=min(0.2, remaining)
        )
        now = time.monotonic()
        if message is not None and message.get_type() == "HEARTBEAT":
            last_heartbeat = now
        elif not _fresh(last_heartbeat, now):
            return "comms_lost"
        if now < next_poll:
            continue
        next_poll = now + CONFIRM_POLL_SECONDS
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
    return "timeout"

#check if the drone is armed
def _armed(heartbeat):
    return bool(heartbeat.base_mode & ARMED)

#check if the heartbeat is fresh
def _fresh(seen_at, now):
    return seen_at is not None and now - seen_at <= FRESH_SECONDS

#check if the drone is ready to launch, return a list of reasons why it is NOT ready
def _readiness_reasons(heartbeat, heartbeat_at, gps, gps_at, status, status_at, now):
    reasons = []
    #hella ifs
    if not _fresh(heartbeat_at, now): 
        reasons.append("Heartbeat missing or stale")
    elif _armed(heartbeat):
        reasons.append("Flight controller is already armed")
    if not _fresh(gps_at, now):
        reasons.append("GPS telemetry missing or stale")
    elif gps.fix_type < 3:
        reasons.append("GPS fix is not 3D")
    if not _fresh(status_at, now):
        reasons.append("Pre-arm status missing or stale")
    elif (status.onboard_control_sensors_health & PREARM) == 0:
        reasons.append("Pre-arm checks have not passed")
    return reasons


def ready_for_launch(link, timeout=READINESS_TIMEOUT):
    #set the deadline for the launch, time out if it takes too long
    deadline = time.monotonic() + timeout
    #initialize the variables for the heartbeat, GPS, and status
    heartbeat = gps = status = None
    heartbeat_at = gps_at = status_at = None
    #while u still have time b4 timeout corner
    while time.monotonic() < deadline:
        #how much time is left before timeout corner
        remaining = deadline - time.monotonic()
        #read the heartbeat, GPS, and status from the drone, if it is not old data
        message = link.recv_match(blocking=True, timeout=min(0.2, remaining))
        now = time.monotonic()

        #if the message is not bad data and exists
        if message is not None and message.get_type() != "BAD_DATA":
            #get the type of the message
            kind = message.get_type()
            if kind == "HEARTBEAT":
                #set the heartbeat and the time it was seen
                heartbeat, heartbeat_at = message, now
            #set the GPS and the time it was seen
            elif kind == "GPS_RAW_INT":
                gps, gps_at = message, now
            #set the status and the time it was seen
            elif kind == "SYS_STATUS":
                status, status_at = message, now

        #we have all the values we need
        have_all_samples = heartbeat is not None and gps is not None and status is not None

        # each timestamp must be recent; one stale sample
        all_fresh = True
        for seen_at in (heartbeat_at, gps_at, status_at):
            if not _fresh(seen_at, now):
                all_fresh = False
                break

        # decide only after all three samples exist and are freshe vals form our readiness reasons
        if have_all_samples and all_fresh:
            reasons = _readiness_reasons(
                heartbeat, heartbeat_at, gps, gps_at, status, status_at, now
            )

            # if len(reasons) == 0, there are NO reasons, drone is ready, if len isnt 0 ready is false 
            ready = len(reasons) == 0
            #either true, and no reasons, or false, and reasons
            return ready, reasons
    #times up return false and reasons
    now = time.monotonic()
    return False, _readiness_reasons(
        heartbeat, heartbeat_at, gps, gps_at, status, status_at, now
    )


#link, desired mode, desired armed state, timeout
def wait_for_aircraft(link, mode, armed, timeout):
    #making sure its within the timeout
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        message = link.recv_match(
            type="HEARTBEAT", blocking=True, timeout=min(0.2, remaining)
        )
        #if we dont get a heartbeat, or the message is not a heartbeat, continue
        if message is None or message.get_type() != "HEARTBEAT":
            continue
        #check if the drone is armed
        seen_armed = _armed(message)
        #check if the drone is in the mode we want, and if it is armed
        if mavutil.mode_string_v10(message) == mode and seen_armed == armed:
            #return no errors
            return
    #if we timed out, or not in the mode we want, or not armed, raise an error
    raise RuntimeError(f"timed out waiting for {mode} armed={armed}")

#sends one MAVlink command to the FC, link, the specific command to the FC, *parameters are the parameters for the command
def _command(link, command, *parameters):
    link.mav.command_long_send(
        link.target_system,
        link.target_component,
        command,
        0,
        *parameters,
    )


# follows the drone's height until it reaches the target or something goes wrong
def confirm_climb(link):
    #set the deadline for the climb, time out if it takes too long (should have leeway with this timeout)
    deadline = time.monotonic() + ALTITUDE_TIMEOUT
    #set the time it started, and the last time it progressed
    started = last_progress = time.monotonic()
    last_position_at = None
    last_heartbeat = None
    best_altitude = None

    #pre timeout corner
    while time.monotonic() < deadline:
        message = link.recv_match(blocking=True, timeout=0.2)
        now = time.monotonic()

        #set position anchor to started, AT THE BEGINING, or set it to the last position if we are on a non-initial loop
        position_anchor = started if last_position_at is None else last_position_at
        #if we dont get a message, or the message is bad data edge check
        if message is None or message.get_type() == "BAD_DATA":
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue

        #get the type of the message (same logic as wait_for_aircraft)
        kind = message.get_type()
        if kind == "HEARTBEAT":
            if mavutil.mode_string_v10(message) != "GUIDED" or not _armed(message):
                raise RuntimeError("Flight controller left GUIDED or disarmed")
            last_heartbeat = now
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        if kind != "GLOBAL_POSITION_INT":
            if now - position_anchor > FRESH_SECONDS:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        last_position_at = now
        if not _fresh(last_heartbeat, now):
            continue
        #unlike wait_for_aircraft, we are waiting for the altitude to reach the target, so check that and check progress
        altitude = message.relative_alt / 1000.0
        #if no best alt or the altitude is better than the best alt + MIN_PROGRESS, set the best alt to the altitude
        if best_altitude is None or altitude >= best_altitude + MIN_PROGRESS:
            best_altitude = altitude
            last_progress = now
        #if the altitude is within the tolerance we are alloting for, we can confirm the climb, also send the altitude
        if altitude >= TARGET_ALTITUDE - ALTITUDE_TOLERANCE:
            return altitude
        #if the last progress is more than the progress timeout, raise an error, continue within the loop
        if now - last_progress > PROGRESS_TIMEOUT:
            raise RuntimeError("No altitude progress")
    #we in da timeout corner --> cant confirm the climb
    raise RuntimeError("Target altitude timeout")

#this function is used to return the details of the launch
# (state, drone_id, arm_requested, takeoff_requested, handoff)
def _result(state, drone_id, **extra):
    result = {
        "state": state,
        "drone_id": drone_id,
        "arm_requested": False,
        "takeoff_requested": False,
        "handoff": None,
    }
    result.update(extra)
    return result

##OUR LAUNCH CODE ----------------------------------------------------------------
# runs the launch steps in order when main.py calls this function
def run_launch(drone_id, table=None, connection_address=FC_PORT, baud_rate=BAUD_RATE):
    #set table value
    if table is None:
        table = missions_table()
    # active and completed are mission states. Only launch_status starts this sequence.
    mission = find_launch_request(table, drone_id)
    if mission is None:
        return _result("NO_LAUNCH_REQUEST", drone_id)
    mission_id = mission["mission_id"]
    #set the values for everything we use in the other functions
    link = None
    result = None
    arm_requested = False
    takeoff_requested = False
    commands_started = False
    #try to launch the drone
    try:
        link = mavutil.mavlink_connection(connection_address, baud=baud_rate)
        #if we dont get a heartbeat, --> send the result as NOT READY
        if link.wait_heartbeat(timeout=10) is None:
            reason = "Flight controller heartbeat missing"
            result = _with_report(
                _result("NOT_READY", drone_id, reason=reason, reasons=[reason]),
                report_launch(
                    table, mission_id, LAUNCH_NOT_READY, reason, [reason]
                ),
            )
            return result

        # heartbeat, GPS, and pre-arm must all pass before any command is sent
        ready, reasons = ready_for_launch(link)
        # readiness failed, so stop. this does not retry
        if not ready:
            result = _with_report(
                _result(
                    "NOT_READY",
                    drone_id,
                    reason="Flight controller is not ready",
                    reasons=reasons,
                ),
                report_launch(
                    table,
                    mission_id,
                    LAUNCH_NOT_READY,
                    "Flight controller is not ready",
                    reasons,
                ),
            )
            return result

        # A row that is already confirmed has passed this wait on an earlier call.
        if mission.get("launch_status") != LAUNCH_CONFIRMED:
            report_error = report_launch(
                table, mission_id, LAUNCH_READY, "Flight controller is ready"
            )
            if report_error:
                result = _with_report(
                    _result(
                        "NOT_READY",
                        drone_id,
                        reason="Could not report ready to the operator",
                    ),
                    report_error,
                )
                return result
            # stay here until the operator confirms. takeoff is still not sent.
            outcome = wait_for_confirmation(table, link, mission_id)
            if outcome == "comms_lost":
                reason = "Communication lost while waiting for operator confirmation"
                result = _with_report(
                    _result("NOT_READY", drone_id, reason=reason, reasons=[reason]),
                    report_launch(
                        table, mission_id, LAUNCH_NOT_READY, reason, [reason]
                    ),
                )
                return result
            if outcome in ("timeout", "read_failed"):
                reason = (
                    "Operator has not confirmed"
                    if outcome == "timeout"
                    else "Could not read operator confirmation"
                )
                result = _result(
                    "AWAITING_CONFIRMATION", drone_id, reason=reason
                )
                return result
            if outcome != "confirmed":
                result = _result(
                    "CONFIRMATION_CANCELLED",
                    drone_id,
                    reason="Operator confirmation was cleared",
                )
                return result
            # the wait can be long, so the pre-arm check has to pass again
            ready, reasons = ready_for_launch(link)
            if not ready:
                result = _with_report(
                    _result(
                        "NOT_READY",
                        drone_id,
                        reason="Flight controller is not ready",
                        reasons=reasons,
                    ),
                    report_launch(
                        table,
                        mission_id,
                        LAUNCH_NOT_READY,
                        "Flight controller is not ready",
                        reasons,
                    ),
                )
                return result

        # look up the GUIDED mode number. this does not send anything yet
        guided = (link.mode_mapping() or {}).get("GUIDED")
        # GUIDED is not in this flight controller's mode list, so no command is sent
        if guided is None:
            reason = "GUIDED mode unavailable"
            result = _with_report(
                _result("NOT_READY", drone_id, reason=reason, reasons=[reason]),
                report_launch(
                    table, mission_id, LAUNCH_NOT_READY, reason, [reason]
                ),
            )
            return result
        # send the mode change
        try:
            link.set_mode(guided)
        # set_mode only writes the frame locally. An exception means that write failed, so SET_MODE never reached the flight controller.
        except Exception as error:
            reason = f"GUIDED frame was not sent: {error}"
            result = _with_report(
                _result(
                    "LAUNCH_FAILED",
                    drone_id,
                    reason=reason,
                ),
                report_launch(
                    table, mission_id, LAUNCH_FAILED_STATUS, reason, [reason]
                ),
            )
            return result
        commands_started = True

        # wait until a heartbeat shows GUIDED and still disarmed
        wait_for_aircraft(link, "GUIDED", False, MODE_TIMEOUT)

        # command_long_send only writes the frame. An exception means the arm command was not sent.
        #try to arm the drone
        try:
            _command(link, ARM, 1, 0, 0, 0, 0, 0, 0)
        except Exception as error:
            reason = f"Arm frame was not sent: {error}"
            result = _with_report(
                _result(
                    "LAUNCH_FAILED",
                    drone_id,
                    reason=reason,
                ),
                report_launch(
                    table, mission_id, LAUNCH_FAILED_STATUS, reason, [reason]
                ),
            )
            return result
        arm_requested = True
        #wait for the drone to be in the GUIDED mode and armed
        wait_for_aircraft(link, "GUIDED", True, ARM_TIMEOUT)

        #READY FOR TAKEOFF----------------------------------------------------------------------------------
        # tells the drone to take off to our target height of 30 feet
        #try to takeoff
        try:
            #send the takeoff command --> actually goes into the air to reach the target altitude
            _command(link, TAKEOFF, 0, 0, 0, 0, 0, 0, TARGET_ALTITUDE)
        except Exception as error:
            reason = f"Takeoff frame was not sent: {error}"
            result = _with_report(
                _result(
                    "LAUNCH_INTERRUPTED",
                    drone_id,
                    reason=reason,
                    arm_requested=True,
                ),
                report_launch(
                    table, mission_id, LAUNCH_FAILED_STATUS, reason, [reason]
                ),
            )
            return result
        takeoff_requested = True

        #confirm the climb
        altitude = confirm_climb(link)
        #send the result
        result = _with_report(
            _result(
                "LAUNCH_SUCCEEDED",
                drone_id,
                altitude_m=altitude,
                handoff="autonomous",
                arm_requested=True,
                takeoff_requested=True,
            ),
            report_launch(
                table,
                mission_id,
                LAUNCH_FINISHED,
                "Climb confirmed",
            ),
        )
        return result

    #if we get an error at any point in the try
    except (RuntimeError, OSError, TimeoutError) as error:
        if commands_started:
            launch_status = LAUNCH_FAILED_STATUS
            state = "LAUNCH_INTERRUPTED" if arm_requested else "LAUNCH_FAILED"
        else:
            launch_status = LAUNCH_NOT_READY
            state = "NOT_READY"
        result = _with_report(
            _result(
                state,
                drone_id,
                reason=str(error),
                arm_requested=arm_requested,
                takeoff_requested=takeoff_requested,
            ),
            report_launch(
                table, mission_id, launch_status, str(error), [str(error)]
            ),
        )
        return result

    #finally, close the link
    finally:
        if link is not None:
            try:
                link.close()
            except Exception as error:
                if result is not None:
                    result["cleanup_error"] = str(error)
