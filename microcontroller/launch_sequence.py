from pymavlink import mavutil
import time


FC_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200

TARGET_ALTITUDE = 9.144  # 30 feet
ALTITUDE_TOLERANCE = 0.5
HEARTBEAT_TIMEOUT = 10


def connect():
    print("Connecting to flight controller...")

    connection = mavutil.mavlink_connection(
        FC_PORT,
        baud=BAUD_RATE
    )

    heartbeat = connection.wait_heartbeat(
        timeout=HEARTBEAT_TIMEOUT
    )

    if heartbeat is None:
        raise RuntimeError(
            "No heartbeat received from flight controller."
        )

    print("Flight controller connected.")
    return connection


def set_guided_mode(connection):
    print("Setting GUIDED mode...")

    mode_id = connection.mode_mapping().get("GUIDED")

    if mode_id is None:
        raise RuntimeError(
            "GUIDED mode is not available."
        )

    connection.set_mode(mode_id)

    while True:
        heartbeat = connection.recv_match(
            type="HEARTBEAT",
            blocking=True,
            timeout=5
        )

        if heartbeat is None:
            raise RuntimeError(
                "Lost heartbeat while changing flight mode."
            )

        if mavutil.mode_string_v10(heartbeat) == "GUIDED":
            print("GUIDED mode confirmed.")
            return


def arm(connection):
    print("Requesting arm...")

    connection.arducopter_arm()

    connection.motors_armed_wait()

    print("Drone armed.")


def takeoff(connection):
    print(
        f"Requesting takeoff to "
        f"{TARGET_ALTITUDE:.2f} meters (30 feet)..."
    )

    connection.mav.command_long_send(
        connection.target_system,
        connection.target_component,
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        TARGET_ALTITUDE
    )


def wait_for_target_altitude(connection):
    print("Monitoring altitude...")

    while True:
        message = connection.recv_match(
            type="GLOBAL_POSITION_INT",
            blocking=True,
            timeout=5
        )

        if message is None:
            raise RuntimeError(
                "No altitude telemetry received."
            )

        # relative_alt is reported in millimeters
        current_altitude = message.relative_alt / 1000.0

        print(
            f"Current altitude: "
            f"{current_altitude:.2f} meters"
        )

        if current_altitude >= (
            TARGET_ALTITUDE - ALTITUDE_TOLERANCE
        ):
            print(
                f"Target altitude reached: "
                f"{current_altitude:.2f} meters"
            )
            return


def main():
    try:
        # 1. Connect to Kakute H7
        connection = connect()

        # 2. Put ArduPilot into GUIDED mode
        set_guided_mode(connection)

        print("Connection and GUIDED mode confirmed.")

        # 3. Arm
        # 4. Send takeoff command
        # 5. Monitor climb to 30 feet

        # Leave these disabled until an approved flight test:
        # arm(connection)
        # takeoff(connection)
        # wait_for_target_altitude(connection)

    except Exception as error:
        print(f"Launch sequence stopped: {error}")


if __name__ == "__main__":
    main()
