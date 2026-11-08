# How far the drone is from the center of a car.
# Shivaji and Corpus
# The center of the camera frame is the drone's view center. Each vehicle box
# already has center_x and center_y from bounding_boxes.py. This file turns
# those two points into an offset and a distance.

from collections import namedtuple
from math import atan, cos, degrees, hypot, radians, sin, tan

import numpy as np

# x and y are pixels. x is from the left edge, y is from the top.
ImageCenter = namedtuple("ImageCenter", ["x", "y"])
# x is how far ray travels right per unit forward, y is how far down per unit forward, z is how far forward
Ray = namedtuple("Ray", ["x", "y", "z"])


def image_center(frame_width, frame_height):
    return ImageCenter(frame_width / 2, frame_height / 2)

# Pixel gap from the center of the picture to the center of the car.
#if image center is at (0,0) and car center is at (100,100) --> make offset_x = 100 and offset_y = 100
#receive vars from bounding_boxes.py
def distance_from_car_center(frame_width, frame_height, car_center_x, car_center_y):
    center = image_center(frame_width, frame_height)
    offset_x = car_center_x - center.x
    offset_y = car_center_y - center.y
    return {
        "drone_center_x": center.x,
        "drone_center_y": center.y,
        "car_center_x": car_center_x,
        "car_center_y": car_center_y,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "distance_px": hypot(offset_x, offset_y),
    }

# Each photo package has what changes with that frame: the photo, the car
# center, the drone's altitude above the level road, and the drone's pitch and roll.
# latitude and longitude are the drone's GPS at the time of that photo. heading
# is degrees clockwise from north.
# The camera argument stays fixed: field of view and how the camera is mounted.
# Frame size, image center, and focal length are computed here.
def ground_distance_m(package, camera):

    photo = package["photo"]
    frame_height, frame_width = photo.shape[:2]
    center = image_center(frame_width, frame_height)
    offset_x = package["center_x"] - center.x
    offset_y = package["center_y"] - center.y
    altitude_m = package["altitude"]
    
    #focal length is the distance from the lens to the image sensor --> help us get the rays
    focal_x = center.x / tan(radians(camera["horizontal_fov"]) / 2)
    focal_y = center.y / tan(radians(camera["vertical_fov"]) / 2)

    #-------------- dealing w rays
    #making our ray based off the offset from the center of image, z is 1 because the ray starts at the lens
    car_ray = Ray(offset_x / focal_x, offset_y / focal_y, 1)
    # modify the ray based off of the roll, use sin on the x because it moves the ray right, cos on the y because it moves the ray down
    roll = radians(package.get("roll", 0))
    car_ray = Ray(
        car_ray.x * cos(roll) - car_ray.y * sin(roll),
        car_ray.x * sin(roll) + car_ray.y * cos(roll),
        car_ray.z,
    )

    # modify the ray based off of the pitch, use cos on the y because it moves the ray down, sin on the z because it moves the ray forward
    pitch = radians(camera["camera_mount"] + package.get("pitch", 0))
    car_ray = Ray(
        car_ray.x,
        car_ray.y * cos(pitch) + car_ray.z * sin(pitch),
        car_ray.y * (-sin(pitch)) + car_ray.z * cos(pitch),
    )
    #if the ray dont even touch the ground js fade the whole thing its ggs
    if car_ray.y <= 1e-9:
        raise ValueError(
            "That pixel looks at or above the horizon, so it does not meet the ground"
        )

    #now looking at distance between drone and car
    #scale takes how high up we are and divides it by the y value (downwards) to get the real life distance
    scale = altitude_m / car_ray.y
    #multiple that scale by how far the ray travels right to see how right it is from the drone in METERS finally
    offset_x_m = scale * car_ray.x
    #same stuff but how far it travels forward(in front of da drone) in meters 
    offset_y_m = scale * car_ray.z
    # take how x left and how y in front !!!!!!!!! and put that jawn into gps coords for Pranav n em 
    return desired_gps(offset_x_m, offset_y_m, package["latitude"], package["longitude"], package["heading"])


# Same radius AssignDrone uses for distances on the Earth.
_EARTH_RADIUS_M = 6371000

#js add offset to the curr gps to get desired gps loc
def desired_gps(offset_x_m, offset_y_m, curr_latitude, curr_longitude, heading_deg):
    heading = radians(heading_deg)
    north_m = offset_y_m * cos(heading) - offset_x_m * sin(heading)
    east_m = offset_y_m * sin(heading) + offset_x_m * cos(heading)
    lat_rad = radians(curr_latitude)
    return {
        "latitude": curr_latitude + degrees(north_m / _EARTH_RADIUS_M),
        "longitude": curr_longitude + degrees(east_m / (_EARTH_RADIUS_M * cos(lat_rad))),
    }





#----
# Temporary stand-in until the Pi stream and the flight controller are connected.
# Sony IMX708, the Camera Module 3 sensor: 4608 x 2592 pixels, 1.4 µ (mu reference) m each.
# The stock lens is not 6 mm. These angles are a 6 mm lens on that sensor.
_PIXEL_SIZE_MM = 0.0014
_FRAME_WIDTH = 4608
_FRAME_HEIGHT = 2592
_LENS_FOCAL_LENGTH_MM = 6.0
_DRONE_ALTITUDE_M = 25 * 0.3048
def _field_of_view(sensor_mm):
    return degrees(2 * atan((sensor_mm / 2) / _LENS_FOCAL_LENGTH_MM))
PI_CAMERA_3_6MM = {
    "horizontal_fov": _field_of_view(_FRAME_WIDTH * _PIXEL_SIZE_MM),
    "vertical_fov": _field_of_view(_FRAME_HEIGHT * _PIXEL_SIZE_MM),
    "camera_mount": 45,
}

#test code
def fake_package(center_x=None, center_y=None, pitch=0, roll=0):
    center = image_center(_FRAME_WIDTH, _FRAME_HEIGHT)
    if center_x is None:
        center_x = center.x
    if center_y is None:
        center_y = center.y
    return {
        "photo": np.zeros((_FRAME_HEIGHT, _FRAME_WIDTH, 3), dtype=np.uint8),
        "center_x": center_x,
        "center_y": center_y,
        "altitude": _DRONE_ALTITUDE_M,
        "pitch": pitch,
        "roll": roll,
        "latitude": 0,
        "longitude": 0,
        "heading": 0,
    }
