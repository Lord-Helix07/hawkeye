# ASSIGNED TO: Tissa + Nandika
# Bounding box logic for detected vehicles.
# Handles vehicle boxes and IDs needed for target selection.
import cv2
#CREATE THE BOX
def create_bounding_boxes(detections):
    """Add a box ID to each detected vehicle."""

    vehicles = []

    for index, detection in enumerate(detections, start=0):
        vehicle = {
            "box_id": index,
            "class_id": detection["class_id"],
            "class_name": detection["class_name"],
            "confidence": detection["confidence"],
            "box": detection["box"]
        }

        vehicles.append(vehicle)

    return vehicles

#DRAWWWW THE BOX
def draw_bounding_boxes(frame, vehicles, selected_box_id=None):
    """Draw a rectangle and label around each detected vehicle."""



    for vehicle in vehicles:
        box = vehicle["box"]

        x1 = box["x"]
        y1 = box["y"]
        x2 = box["width"]
        y2 = box["height"]

        # Use red for the selected vehicle and green for others.
        if vehicle["box_id"] == selected_box_id:
            color = (0, 0, 255)
        else:
            color = (0, 255, 0)

        # Draw the rectangle around the vehicle.
        cv2.rectangle(
            frame,
            (x1, y1),
            (x1 + x2, y1 + y2),
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


