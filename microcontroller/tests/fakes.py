"""Mock flight-controller links and MAVLink messages."""

from pymavlink import mavutil

import landing_sequence
import launch_sequence

MAV = mavutil.mavlink
ARM = MAV.MAV_CMD_COMPONENT_ARM_DISARM
TAKEOFF = MAV.MAV_CMD_NAV_TAKEOFF
ACCEPTED = MAV.MAV_RESULT_ACCEPTED
IN_PROGRESS = MAV.MAV_RESULT_IN_PROGRESS
DENIED = MAV.MAV_RESULT_DENIED
FAILED = MAV.MAV_RESULT_FAILED
ON_GROUND = MAV.MAV_LANDED_STATE_ON_GROUND
IN_AIR = MAV.MAV_LANDED_STATE_IN_AIR
GUIDED = 4
STABILIZE = 0
LOITER = 5
LAND = 9
READ_LIMIT = 5000

SENSOR_MASK = (
    MAV.MAV_SYS_STATUS_SENSOR_3D_GYRO
    | MAV.MAV_SYS_STATUS_SENSOR_3D_ACCEL
    | MAV.MAV_SYS_STATUS_SENSOR_3D_MAG
    | MAV.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE
    | MAV.MAV_SYS_STATUS_SENSOR_GPS
)
PREARM = MAV.MAV_SYS_STATUS_PREARM_CHECK

BATTERY_CONFIG = {
    "battery_id": 0,
    "battery_format": "pack",
    "min_voltage": 14.0,
}


class Msg:
    def __init__(self, kind, **fields):
        self._kind = kind
        for name, value in fields.items():
            setattr(self, name, value)

    def get_type(self):
        return self._kind


class FakeMav:
    def __init__(self, link):
        self.link = link

    def command_long_send(self, *args):
        self.link.commands.append(args)


class FakeLink:
    """Scripted MAVLink endpoint. Reads advance the virtual clock."""

    def __init__(self, clock, default=None, queued=None):
        self.clock = clock
        self.default = default or (lambda link: None)
        self.queued = list(queued or [])
        self.commands = []
        self.modes = []
        self.closed = False
        self.close_count = 0
        self.reads = 0
        self.fail_set_mode = False
        self.mav = FakeMav(self)
        self.target_system = 1
        self.target_component = 1

    def mode_mapping(self):
        return {
            "STABILIZE": STABILIZE,
            "GUIDED": GUIDED,
            "LOITER": LOITER,
            "LAND": LAND,
        }

    def set_mode(self, mode_id):
        self.modes.append(mode_id)
        if self.fail_set_mode:
            raise RuntimeError(
                "set_mode failed before completion"
            )

    def close(self):
        self.closed = True
        self.close_count += 1

    def wait_heartbeat(self, timeout=None):
        return getattr(self, "heartbeat_result", heartbeat(GUIDED, False))

    def recv_match(self, blocking=True, timeout=0.2, **kwargs):
        self.reads += 1
        if self.reads > READ_LIMIT:
            raise RuntimeError("mock read limit reached")
        if self.raise_on_read:
            raise RuntimeError("serial read failed")
        if self.queued:
            message = self.queued.pop(0)
            self.clock.advance(0.05)
            return message
        message = self.default(self)
        self.clock.advance(0.05 if message is not None else 0.25)
        return message

    @property
    def raise_on_read(self):
        return getattr(self, "_raise_on_read", False)

    @raise_on_read.setter
    def raise_on_read(self, value):
        self._raise_on_read = value


def heartbeat(custom_mode, armed):
    base_mode = MAV.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    if armed:
        base_mode |= MAV.MAV_MODE_FLAG_SAFETY_ARMED
    return Msg(
        "HEARTBEAT",
        type=MAV.MAV_TYPE_QUADROTOR,
        autopilot=MAV.MAV_AUTOPILOT_ARDUPILOTMEGA,
        base_mode=base_mode,
        custom_mode=custom_mode,
        system_status=MAV.MAV_STATE_STANDBY,
    )


def sys_status(prearm_enabled=True, prearm_healthy=True, sensors_healthy=True):
    enabled = SENSOR_MASK
    healthy = SENSOR_MASK if sensors_healthy else 0
    if prearm_enabled:
        enabled |= PREARM
    if prearm_healthy:
        healthy |= PREARM
    return Msg(
        "SYS_STATUS",
        onboard_control_sensors_enabled=enabled,
        onboard_control_sensors_health=healthy,
    )


def battery(mv=16000):
    return Msg(
        "BATTERY_STATUS",
        id=0,
        voltages=[mv],
        voltages_ext=[],
        charge_state=MAV.MAV_BATTERY_CHARGE_STATE_UNDEFINED,
    )


def gps(fix_type=3):
    return Msg("GPS_RAW_INT", fix_type=fix_type)


def position(relative_mm):
    return Msg("GLOBAL_POSITION_INT", relative_alt=relative_mm)


def ack(command, result):
    return Msg("COMMAND_ACK", command=command, result=result)


def extended(landed_state):
    return Msg("EXTENDED_SYS_STATE", landed_state=landed_state)


def commands_named(link, command):
    return [args for args in link.commands if args[2] == command]


def launch_stream(plan):
    state = {
        "index": 0,
        "arm_ack": False,
        "takeoff_acks": 0,
        "alt": plan.get("alt_mm", 300),
    }
    cycle = (
        "HEARTBEAT",
        "SYS_STATUS",
        "BATTERY_STATUS",
        "GPS_RAW_INT",
        "GLOBAL_POSITION_INT",
    )
    takeoff_results = plan.get("takeoff_results", [ACCEPTED])

    def default(link):
        arm_sent = bool(commands_named(link, ARM))
        takeoff_sent = bool(commands_named(link, TAKEOFF))
        if arm_sent and not state["arm_ack"]:
            state["arm_ack"] = True
            return ack(ARM, plan.get("arm_result", ACCEPTED))
        if (
            takeoff_sent
            and state["takeoff_acks"] < len(takeoff_results)
        ):
            result = takeoff_results[state["takeoff_acks"]]
            state["takeoff_acks"] += 1
            return ack(TAKEOFF, result)

        kind = cycle[state["index"] % len(cycle)]
        state["index"] += 1
        armed = arm_sent and plan.get("armed_after_arm", True)
        if takeoff_sent and plan.get("disarm_after_takeoff"):
            armed = False
        mode = plan.get("mode", GUIDED)
        if arm_sent:
            mode = plan.get("mode_after_arm", mode)
        if takeoff_sent:
            mode = plan.get("mode_after_takeoff", mode)
        if kind == "HEARTBEAT":
            return heartbeat(mode, armed)
        if kind == "SYS_STATUS":
            return sys_status()
        if kind == "BATTERY_STATUS":
            return battery()
        if kind == "GPS_RAW_INT":
            return gps()
        if takeoff_sent and plan.get("climb"):
            state["alt"] = min(state["alt"] + 2500, 9500)
        return position(state["alt"])

    return default


def landing_stream(plan):
    state = {
        "index": 0,
        "heartbeats_after_mode": 0,
        "touchdown": False,
    }

    def default(link):
        state["index"] += 1
        slot = state["index"] % 3
        armed = plan.get("armed", True)
        landed = plan.get("landed", IN_AIR)
        mode = plan.get("mode", GUIDED)
        alt = plan.get("alt_mm", 25000)
        phase = plan.get("after_mode")
        if state["touchdown"]:
            armed = False
            landed = ON_GROUND
            mode = LAND
            alt = plan.get("touchdown_alt_mm", 25000)
        if slot == 1 and link.modes:
            state["heartbeats_after_mode"] += 1
            seen = state["heartbeats_after_mode"]
            if phase == "land_then_loiter":
                mode = LAND if seen == 1 else LOITER
            elif phase == "land_then_touchdown":
                mode = LAND
                if seen >= 2:
                    state["touchdown"] = True
                    armed = False
                    landed = ON_GROUND
                    alt = plan.get("touchdown_alt_mm", 25000)
        if slot == 1:
            return heartbeat(mode, armed)
        if slot == 2:
            return position(alt)
        return extended(landed)

    return default


def prime_ready(cache, clock, *, armed=False, mode=GUIDED, alt_mm=300,
                prearm_enabled=True, prearm_healthy=True,
                sensors_healthy=True, fix_type=3, voltage_mv=16000):
    now = clock.now
    hb = heartbeat(mode, armed)
    status = sys_status(
        prearm_enabled=prearm_enabled,
        prearm_healthy=prearm_healthy,
        sensors_healthy=sensors_healthy,
    )
    bat = battery(voltage_mv)
    cache.messages = {
        "HEARTBEAT": (hb, now, 1),
        "SYS_STATUS": (status, now, 1),
        "GPS_RAW_INT": (gps(fix_type), now, 1),
        "GLOBAL_POSITION_INT": (position(alt_mm), now, 1),
    }
    cache.batteries = {0: (bat, now)}
    cache.faults = []
    return cache


def run_scripted_launch(monkeypatch, clock, link, **kwargs):
    monkeypatch.setattr(
        launch_sequence,
        "connect",
        lambda address, baud: link,
    )
    options = {
        "connection_address": "mock://fc",
        "baud_rate": 115200,
        "config": BATTERY_CONFIG,
        "execute_flight": True,
        "simulation_confirmed": True,
        "allow_hardware_flight": False,
        "auto_recovery_land": False,
    }
    options.update(kwargs)
    return launch_sequence.run_launch(**options)


def run_scripted_landing(monkeypatch, link, **kwargs):
    monkeypatch.setattr(
        landing_sequence,
        "connect",
        lambda address, baud: link,
    )
    options = {
        "connection_address": "mock://fc",
        "baud_rate": 115200,
        "execute_landing": True,
        "simulation_confirmed": True,
        "allow_hardware_landing": False,
    }
    options.update(kwargs)
    return landing_sequence.run_landing(**options)
