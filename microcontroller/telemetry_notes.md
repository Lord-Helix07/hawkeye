1. A MAVlink heartbeat is a continuous and reccurring indication that the FC is powered on and responding to the connection
2. The PI can confirm connection by seeing if heartbeats arrive in a given time period
3. The Pi reads a file to identify the flight mode and checks a different file to determine whether the drone is armed
4. If the heartbeats stop, the PI will report a connection timeout, mark its current flight mode, and send an alert to the backend SWE team's code
5. The team's goal is to decide the heartbeat timeout, the required flight modes, how to report the status of the sensors, and what actions to take if communication is lost while in armed mode
