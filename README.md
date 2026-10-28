# hawkeye
Police Pursuit Drone Fall 2026 Omicron

# ReadME Rules:
Will be updated at the end of every week with everyones contributions

## Tech Stack

### Frontend

* React
* JavaScript / JSX
* HTML/CSS
* Figma for UI/UX design

#### Running the frontend

```
cd frontend
npm install
npm run dev
```

Then open the `localhost` link it prints. Pages live in `frontend/src/pages/` (each with its own `.css`), and `frontend/src/App.jsx` switches between them.

### Computer Vision

* Python
* YOLO11
* OpenCV
* ByteTrack (planned for later tracking work)

### Backend / Cloud

* Python
* REST/HTTPS APIs
* AWS Lambda (planned)
* Amazon DynamoDB (planned)
* Amazon S3 (planned where image/file storage is required)

### Drone / Onboard Software

* Raspberry Pi
* Python
* Computer vision inference pipeline
* Flight-controller communication

## Week 1 Assignments

The goal for Week 1 is to get the major software pieces developing in parallel. Teams should focus on their assigned subsystem rather than waiting for another subsystem to be completed.

### Frontend Team

**Assigned to:** Sona, Alvina, Sravani, Nakpil, Grace

Build the three initial screens based on the approved Figma designs.

#### `screen1.jsx` — Target Selection

Build the interface where the officer can view detected vehicles and select the vehicle that should become the pursuit target.

The actual computer-vision system does not need to be finished yet. Mock vehicle/bounding-box data can be used during development.

#### `screen2.jsx` — Live Pursuit Map

Build the main pursuit interface showing the drone/target location and relevant pursuit information.

Use mock location/status data until the backend is available.

#### `screen3.jsx` — Visual Contact Lost

Build the interface shown when the drone loses visual contact with the selected target.

Follow the approved Figma design and use mock states where backend information is not yet available.

---

### Object Detection

**Assigned to:** Ayush + Jay

`object_detection.py`

Focus on understanding and developing the vehicle detection pipeline.

Week 1 work includes:

* Learn and test the YOLO detection pipeline.
* Run vehicle detection using a pretrained model.
* Understand the model training process and dataset format.
* Begin determining how our vehicle data will eventually be incorporated.
* Produce detection outputs that can later be connected to the bounding-box/target-selection system.

Do not worry about implementing the full tracking system yet.

---

### Bounding Boxes

**Assigned to:** Tissa + Nandika

`bounding_boxes.py`

Develop the logic needed to represent detected vehicles as selectable bounding boxes.

Week 1 work should focus on:

* Understanding how detection outputs translate into bounding boxes.
* Representing each detected vehicle with its bounding-box coordinates.
* Assigning an ID to each detected vehicle/box.
* Creating an output format that can eventually be consumed by the frontend.

The object-detection model does not need to be finished for this work to begin. Mock detection outputs can be used for development and testing.

---

### Backend / Database

**Assigned to:** AWS / Database Team

`database.py`

The priority this week is local backend and schema design — NOT AWS deployment.

The team should:

* Determine what information needs to be stored.
* Design the initial schema/data structures.
* Determine how pursuits, drones, missions, statuses, and related information should be represented.
* Implement/test the design locally.
* Push the local implementation to GitHub for review.