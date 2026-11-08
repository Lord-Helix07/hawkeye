import fc_status
from launch_sequence import prepare_command
from pymavlink import mavutil

LAND_MODE_TIMEOUT = 10


# asks the flight controller to use LAND mode and gets confirmation from fc_status
def request_land_mode(controller):
    mode_id = (controller.connection.mode_mapping() or {}).get("LAND")
    if mode_id is None:
        return fc_status.make_status(
            "LANDING_NOT_AVAILABLE", "LAND mode is unavailable.",
            request_attempted=False, write_completed=False, land_confirmed=False,
        )
    # clear old replies before sending the new mode request
    sequence = prepare_command(controller)
    try:
        controller.connection.set_mode(mode_id)
    except Exception as error:
        return fc_status.make_status(
            "LANDING_OUTCOME_UNKNOWN", "LAND write outcome uncertain: " + str(error),
            request_attempted=True, write_completed=None, land_confirmed=False,
        )
    try:
        controller.confirm_state(
            mode="LAND", timeout=LAND_MODE_TIMEOUT, wait_for_change=True,
            after=sequence, command=mavutil.mavlink.MAV_CMD_DO_SET_MODE,
        )
    except fc_status.CommandRejected as error:
        return fc_status.make_status(
            "LANDING_REJECTED", str(error),
            request_attempted=True, write_completed=True, land_confirmed=False,
        )
    except Exception as error:
        return fc_status.make_status(
            "LANDING_OUTCOME_UNKNOWN", str(error),
            request_attempted=True, write_completed=True, land_confirmed=False,
        )
    return fc_status.make_status(
        "LAND_CONFIRMED", "LAND mode confirmed; touchdown is not monitored here.",
        request_attempted=True, write_completed=True, land_confirmed=True,
    )


# runs the landing request when main.py calls it
def run_landing(connection_address=fc_status.FC_PORT, baud_rate=fc_status.BAUD_RATE,
                execute_landing=False, simulation_confirmed=False,
                allow_hardware_landing=False):
    if not execute_landing:
        return fc_status.make_status("LANDING_DISABLED", request_attempted=False)
    if simulation_confirmed == allow_hardware_landing:
        return fc_status.make_status("AUTHORIZATION_REQUIRED", request_attempted=False)
    controller = None
    try:
        controller = fc_status.FlightController.open(connection_address, baud_rate)
        aircraft = controller.confirm_state()
        if aircraft["flight_mode"] == "LAND":
            return fc_status.make_status(
                "LAND_CONFIRMED", "Already in LAND mode; touchdown is not monitored here.",
                request_attempted=False, write_completed=False, land_confirmed=True,
            )
        if aircraft["armed"] is False:
            return fc_status.make_status(
                "LANDING_NOT_STARTED", "Aircraft is disarmed; touchdown is not verified.",
                request_attempted=False, write_completed=False, land_confirmed=False,
            )
        return request_land_mode(controller)
    except Exception as error:
        return fc_status.make_status(
            "LANDING_FAILED_TO_START", str(error), request_attempted=False,
            write_completed=False, land_confirmed=False,
        )
    finally:
        if controller is not None:
            controller.close()
