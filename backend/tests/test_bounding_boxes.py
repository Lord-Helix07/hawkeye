from backend.bounding_boxes import create_bounding_boxes


def test_create_bounding_boxes():
    detections = [
        {
            "class_id": 2,
            "class_name": "car",
            "confidence": 0.93,
            "box": {
                "x": 420,
                "y": 210,
                "width": 180,
                "height": 120
            }
        }
    ]

    vehicles = create_bounding_boxes(detections)

    assert len(vehicles) == 1
    assert vehicles[0]["box_id"] == 1
    assert vehicles[0]["class_name"] == "car"
    assert vehicles[0]["box"]["width"] == 180