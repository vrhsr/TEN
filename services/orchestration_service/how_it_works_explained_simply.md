# How the Demographics Agent Works (Explained Simply!)

Welcome! If you were to think of the Demographics Agent like a smart robotic assistant working at a doctor's office, here is exactly what it does from start to finish.

---

### 1. The Knock on the Door (How it starts!)
* **What happens:** The system boss (named "Temporal") knocks on our robot's door and hands it a folder. Temporal says, *"Hey, look at Task 21 for Case 13!"*
* **Where this happens in the code:** Temporal sends a message to our `/v1/tasks/advance` web door. Because we just updated the code, Temporal gives us both the `task_id` and the `case_id` right at the door so we don't have to go searching for it.

### 2. Gathering the Clues (Node 1: Fetching Facts)
* **What happens:** Our robot takes Case 13 and walks over to the giant filing cabinets (the Staging APIs). It asks, *"Give me everything you know about this patient!"*
* **The Result:** The cabinet hands back 3 important clues (we call them "Facts"):
  1. The Patient's main file.
  2. The Patient's Demographics file (address, phone number).
  3. The Patient's Insurance file. 
* *Our robot writes down exactly what it did in a magical notebook called "Step History" so the boss can see it was working.*

### 3. The "Evil Twin" Test (Node 2: Target Duplicate Check)
* **What happens:** Before doing any real work, our robot looks at the patient's name and birthdate and stops to think: *"Wait... have we seen this person before under a different file?"* 
* **The Result:** The robot sends the name and birthdate to a special Twin-Detector machine (the `/duplicate-check` API). 
  - If the machine beeps and says **"YES, Twin Found!"**, the robot stops everything, sends the file to a Human worker to fix, and logs an error to the notebook.
  - If the machine says **"NO, they are unique!"**, the robot happily moves to the next step.

### 4. The Grand Checklist (Node 3: Verify Demographics & Insurance)
* **What happens:** Now the robot sits at a desk, puts on its glasses, and looks at the rules to decide where this folder belongs next.
* **The Questions it Asks:**
  1. **"Are they paying with their own cash (Self-Pay)?"** 
     - If yes, close the folder. No insurance work needed!
  2. **"Do they have an address and real insurance listed?"**
     - If no, the robot tosses the folder into the "Missing Registration Info" bin.
  3. **"Is their insurance fresh?"** (Has it been checked by a human in the last 30 days?)
     - If it's *old* (stale), the robot tosses the folder to the "Check Insurance Again" bin (`ELIGIBILITY_VERIFICATION_QUEUE`).
     - If it's *fresh*, the robot tosses the folder into the "Ready for Billing" bin (`CLAIM_CREATION`).

### 5. Reporting Back to the Boss (Finished!)
* **What happens:** Our robot has made its decision! Let's say the insurance was old. The robot runs back to the system boss (Temporal) and says, *"I finished Task 21! The outcome is 'Eligibility is Stale'. Please move Case 13 into the Check-Insurance-Again basket!"*
* **Where this happens in the code:** The robot sends this final message to the `POST /tasks/21/process` API endpoint. Temporal takes the folder, does exactly what the robot asked, and prints out a brand new task for the next worker in line.

And that's it! Our robot sits back down, drinks some oil, and waits for another knock on the door. 🤖🏥
