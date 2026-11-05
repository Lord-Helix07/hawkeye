Launch Sequence
Steps the Rasberry Pi should follow after reciveing launch request and before the takeoff command is sent.
1. The rasbberry Pi recieves a launch request for the assignned drone 
2. Checking if the rasberry pi can communicate with the kakute h7 flight controller.
Confirm that the MavLink communication is working.
If comms fail, report that the drone isn't ready and give the communication failure as the reason
3. Check the flight controller readiness
If the communication is working, we check the status report by the flight controller 
We determine whether the flight conroller reported that its ready
If its not ready, report that the drone isnt ready and include the reason thats reported by the flight controller itself 
4. If communication is working and the flight controller reports that it is ready, report "ready"
if not then report "not ready" with a reason
5. After reporting ready, wait for confirmation from the operator 
Don't send takeoff command while waiting for confirmation 
Questions : How will the rasberry pi recieve the launch requested status from backend?
whats gonna happen if comms gets lost while its still waiting for operator confirmation? 