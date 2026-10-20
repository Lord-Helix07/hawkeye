# ASSIGNED TO: Tissa + Nandika
# Bounding box logic for detected vehicles --> makes and draws
import cv2



#CREATE THE BOX
def create_bounding_boxes(detections):
    """Add a box ID to each detected vehicle."""

    vehicles = []

    #Note: ids are only starting at 1 this MUST be changed later when we start using persistent IDs via the bytetrack jawny
    for index, detection in enumerate(detections, start=1):
        vehicle = {
            "box_id": index,
            "class_id": detection["class_id"],
            "class_name": detection["class_name"],
            "confidence": detection["confidence"],
            "x1": detection["x1"],
            "y1": detection["y1"],
            "x2": detection["x2"],
            "y2": detection["y2"],
            "width": detection["width"],
            "height": detection["height"],
        }

        vehicles.append(vehicle)

    return vehicles

#DRAWWWW THE BOX
def draw_bounding_boxes(frame, vehicles, selected_box_id=None):
    """Draw a rectangle and label around each detected vehicle."""

    for vehicle in vehicles:
        x1 = round(vehicle["x1"])
        y1 = round(vehicle["y1"])
        x2 = round(vehicle["x2"])
        y2 = round(vehicle["y2"])

        # Use red for the selected vehicle and green for others.
        if vehicle["box_id"] == selected_box_id:
            color = (0, 0, 255)
        else:
            color = (0, 255, 0)

        # Draw the rectangle around the vehicle.
        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            color,
        )

        # Create a label above the rectangle.
        label = (
            f'{vehicle["class_name"]} '
            f'#{vehicle["box_id"]} '
            f'({vehicle["confidence"]:.0%})'
        )

        cv2.putText(
            frame,
            label,
            (x1, max(y1 - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
        )

    return frame


