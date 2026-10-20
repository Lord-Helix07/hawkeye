from backend.bounding_boxes import create_bounding_boxes


def test_create_bounding_boxes():
    detections = [
        {
            "class_id": 2,
            "class_name": "car",
            "confidence": 0.93,
            "x1": 420,
            "y1": 210,
            "x2": 600,
            "y2": 330,
            "width": 180,
            "height": 120,
        }
    ]

    vehicles = create_bounding_boxes(detections)

    assert len(vehicles) == 1
    assert vehicles[0]["box_id"] == 1
    assert vehicles[0]["class_name"] == "car"
    assert vehicles[0]["x1"] == 420
    assert vehicles[0]["x2"] == 600
    assert vehicles[0]["width"] == 180
    assert vehicles[0]["height"] == 120