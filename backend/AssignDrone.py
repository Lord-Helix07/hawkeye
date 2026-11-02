import json
import os
import sys 

import httpx # Sends HTTP requests to FastAPI.


def prompt_id(label): # user input for an ID
    value = input(label).strip()
    while not value:
        print('An ID is required.')
        value = input(label).strip()
    return value


def main(): 
    try: #Main Code for drone through FastAPI assignment
        mission_id = prompt_id('Enter the mission ID: ')
        base_url = os.getenv('HAWKEYE_API_URL', 'http://127.0.0.1:8000').rstrip('/') #API address in use
        response = httpx.post(base_url + '/assignments', # Send only the mission ID; the backend selects the drone.
            json={'mission_id': mission_id}, timeout=20)
        response.raise_for_status() #error if unsuccessful HTTP status
        print(json.dumps(response.json(), indent=2))
        return 0
    except httpx.HTTPStatusError as error:  # Display the server's status code and explanation.
        print(f'Assignment failed (HTTP {error.response.status_code}): {error.response.text}', file=sys.stderr)
        return 1
    except httpx.RequestError: #connection error
        print('Could not confirm the request. Check FastAPI/Live Share. Refresh the webpage before retrying: it may already be saved.', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError): # user cancellation 
        print('\nCancelled.', file=sys.stderr)
        return 1


if __name__ == '__main__': # Runs the main code when ran directly
    sys.exit(main())
