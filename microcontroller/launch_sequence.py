"""Command GUIDED, arm, and climb to 30 feet; fc_status owns health checks."""
import time
from pymavlink import mavutil
import fc_status

TARGET_ALTITUDE = 9.144  # meters relative to home (30 feet)
ALTITUDE_TOLERANCE = 0.5
MODE_TIMEOUT = 10
ARM_TIMEOUT = 15
COMMAND_ACK_TIMEOUT = 5
ALTITUDE_TIMEOUT = 45
PROGRESS_TIMEOUT = 12
MIN_PROGRESS = 0.25

# clears old messages so we don't mix up replies to different commands
def prepare_command(cache):
    # Drain frames already waiting before this command.
    # BAD_DATA must not terminate the drain: a malformed frame can
    # sit ahead of an old ACK, and stopping there would let that ACK
    # be read later as the response to the new command. None means
    # the receive had nothing; any other return means keep going,
    # until this deadline.
    deadline = time.monotonic() + 0.3

    while time.monotonic() < deadline:
        message = cache.update(timeout=0)

        if message is None:
            break

    # ignore ACKs already in our cache
    cache.acks.clear()

    return cache.sequence

# waits for the flight controller's reply to the command we just sent
def wait_for_ack(cache, command, start_sequence):
    deadline = time.monotonic() + COMMAND_ACK_TIMEOUT
    last_result = "UNKNOWN"

    while time.monotonic() < deadline:
        cache.update()

        matching = [
            (ack, number)
            for ack, _, number in cache.acks
            if number > start_sequence
            and ack.command == command
        ]

        for ack, number in matching:
            start_sequence = max(start_sequence, number)

            if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return "ACCEPTED"

            if ack.result == mavutil.mavlink.MAV_RESULT_IN_PROGRESS:
                last_result = "IN_PROGRESS"
                continue

            return "REJECTED"

    return last_result


# gets confirmation from fc_status, then sends the command and waits for a reply
def send_command(controller, command, *parameters):
    sequence = prepare_command(controller)
    connection = controller.connection
    if command == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF:
        controller.confirm_state(mode="GUIDED", armed=True)
    elif command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
        controller.confirm_state(mode="GUIDED", armed=False)
    connection.mav.command_long_send(
        connection.target_system, connection.target_component,
        command, 0, *parameters,
    )
    return wait_for_ack(controller, command, sequence)


# sends the arm command and lets fc_status confirm the drone is armed
def arm(controller):
    ack = send_command(
        controller, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        1, 0, 0, 0, 0, 0, 0,
    )
    if ack == "REJECTED":
        raise RuntimeError("Arming rejected by ArduPilot")
    controller.confirm_state(
        mode="GUIDED", armed=True, timeout=ARM_TIMEOUT, wait_for_change=True,
    )


# tells the drone to take off to our target height of 30 feet
def takeoff(controller):
    return send_command(
         controller, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        0, 0, 0, 0, 0, 0, TARGET_ALTITUDE,
    )


# follows the drone's height until it reaches the target or something goes wrong
def monitor_climb(controller, after):
    deadline = time.monotonic() + ALTITUDE_TIMEOUT
    last_progress = time.monotonic()
    best_altitude = None
    while time.monotonic() < deadline:
        controller.update()
        controller.require_state(mode="GUIDED", armed=True)
        position = controller.fresh_after("GLOBAL_POSITION_INT", after)
        if position is None:
            if time.monotonic() - last_progress > fc_status.TELEMETRY_MAX_AGE:
                raise RuntimeError("Altitude telemetry missing or stale")
            continue
        altitude = position.relative_alt / 1000.0
        if best_altitude is None or altitude >= best_altitude + MIN_PROGRESS:
            best_altitude = altitude
            last_progress = time.monotonic()
        if altitude >= TARGET_ALTITUDE - ALTITUDE_TOLERANCE:
            return altitude
        if time.monotonic() - last_progress > PROGRESS_TIMEOUT:
            raise RuntimeError("No altitude progress")
    raise RuntimeError("Target altitude timeout")


# runs the launch steps in order when main.py calls this function
def run_launch(connection_address=fc_status.FC_PORT, baud_rate=fc_status.BAUD_RATE,
               config=None, *, execute_flight=False, operator_confirmed=False,
               simulation_confirmed=False, allow_hardware_flight=False):
    if not execute_flight:
        return {"state": "FLIGHT_DISABLED"}
    if simulation_confirmed == allow_hardware_flight:
        return {"state": "AUTHORIZATION_REQUIRED"}
    if operator_confirmed is not True:
        return {"state": "CONFIRMATION_REQUIRED"}
    if config is None:
        return {"state": "NOT_READY", "reasons": ["Status-health configuration required"]}
    controller = None
    arm_requested = False
    takeoff_requested = False
    try:
        controller = fc_status.FlightController.open(connection_address, baud_rate)
        ready, reasons = controller.wait_ready(config)
        if not ready:
            return {"state": "NOT_READY", "reasons": reasons}
        connection = controller.connection
        guided = (connection.mode_mapping() or {}).get("GUIDED")
        if guided is None:
            raise RuntimeError("GUIDED mode unavailable")
        connection.set_mode(guided)
        controller.confirm_state(
            mode="GUIDED", armed=False, timeout=MODE_TIMEOUT, wait_for_change=True,
        )
        ready, reasons = controller.ready(config)
        if not ready:
            return {"state": "NOT_READY", "reasons": reasons}
        # Once a command is attempted, a write error can leave its outcome unknown.
        arm_requested = True
        arm(controller)
        takeoff_requested = True
        ack = takeoff(controller)
        if ack == "REJECTED":
            raise RuntimeError("Takeoff rejected by ArduPilot")
        altitude = monitor_climb(controller, controller.sequence)
        return {
            "state": "LAUNCH_SUCCEEDED", "altitude_m": altitude, "takeoff_ack": ack,
        }
    except Exception as error:
        return {
            "state": "LAUNCH_INTERRUPTED" if arm_requested else "LAUNCH_FAILED",
            "reason": str(error), "arm_requested": arm_requested,
            "takeoff_requested": takeoff_requested,
        }
    finally:
        if controller is not None:
            controller.close()
