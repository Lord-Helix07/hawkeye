#Shivaij Ganesh
#This program reads the Drones table and groups the rows for the frontend.
#It will be tested in this file currently via terminal.

from database.database import get_dynamodb_resource


# low bat level (cud be adjustable later)
LOW_BATTERY_PERCENT = 20

#all the fields we wanna display
def drone_record(item):
    """Return the fields the frontend needs for one drone."""
    return (
        item["drone_id"],
        int(item["battery_pct"]),
        float(item["latitude"]),
        float(item["longitude"]),
        item["availability"],
    )


def view_drones():
    """Read every drone and return available, unavailable, and low-battery tuples.

    Each drone tuple is (drone_id, battery_pct, latitude, longitude, availability).
    A low-battery drone is left out of the available group. A drone can be both
    unavailable and low battery.
    """
    #get stuff from the drone table
    items = get_dynamodb_resource().Table("Drones").scan().get("Items", [])
    records = [drone_record(item) for item in items]
    #available drones
    available = tuple(
        record for record in records
        if record[4] == "available" and record[1] > LOW_BATTERY_PERCENT
    )
    unavailable = tuple(record for record in records if record[4] != "available")
    low_battery = tuple(record for record in records if record[1] <= LOW_BATTERY_PERCENT)
    return available, unavailable, low_battery

#print 1 drone and its data formatted
def print_drone_group(title, drones):
    print(title)
    if not drones:
        print("(none)")
        return
    for drone_id, battery_pct, latitude, longitude, availability in drones:
        print(
            f"{drone_id}  battery {battery_pct}%  "
            f"location ({latitude}, {longitude})  {availability}"
        )


if __name__ == "__main__":
    available, unavailable, low_battery = view_drones()
    print_drone_group("All Available drones", available)
    print()
    print_drone_group("All Unavailable drones", unavailable)
    print()
    print_drone_group("all Low battery drones", low_battery)
