from canvasapi import Canvas
from datetime import datetime
import json

# Set up the Canvas API connection
#API_URL = 'https://youruniversity.instructure.com'
API_URL = 'https://canvas.ucsc.edu'
API_KEY = 'your_canvas_api_key'
canvas = Canvas(API_URL, API_KEY)

# Get the current authenticated user (no need for user ID)
user = canvas.get_user('self')  # Automatically gets the current user

# Get the list of courses the student is enrolled in
courses = user.get_courses(enrollment_state='active')

# Get current time (in the same timezone as Canvas)
now = datetime.now()

# Create dictionaries to store assignments by class
completed_assignments = {}
pending_assignments = {}
no_due_date_assignments = {}

# Iterate over each course and filter out courses that have ended
for course in courses:
    if hasattr(course, 'end_at') and course.end_at:
        # Only include courses that haven't ended yet
        course_end_date = datetime.strptime(course.end_at, "%Y-%m-%dT%H:%M:%SZ")
        print(f"Course {course.name} ends on {course_end_date}")
        if course_end_date < now:
            continue  # Skip the course if it has already ended
    else:
        print(f"Course {course.name} has no end date")

    # Fetch assignments for the course
    assignments = course.get_assignments()
    
    # Initialize lists for completed and pending assignments for this course
    completed_assignments[course.name] = []
    pending_assignments[course.name] = []
    no_due_date_assignments[course.name] = []
    
    # Iterate over assignments and categorize them
    for assignment in assignments:
        submission = assignment.get_submission(user)  # Get the submission object for the current user
        status = submission.workflow_state  # Status can be 'submitted', 'unsubmitted', etc.
        
        # Handle unsubmitted and submitted assignments
        if status == 'submitted':
            completed_assignments[course.name].append(assignment)
        else:
            # Handle due date filtering
            if hasattr(assignment, 'due_at') and assignment.due_at:
                due_date = datetime.strptime(assignment.due_at, "%Y-%m-%dT%H:%M:%SZ")
                if due_date < now:
                    continue  # Skip assignments that are past due
                else:
                    pending_assignments[course.name].append(assignment)
            else:
                # Handle assignments with no due date
                no_due_date_assignments[course.name].append(assignment)

# Output results
print("Completed Assignments:")
for course_name, assignments in completed_assignments.items():
    print(f"\nCourse: {course_name}")
    for assignment in assignments:
        # Check if 'submitted_at' exists (i.e., if the assignment was actually submitted)
        if hasattr(assignment, 'submitted_at') and assignment.submitted_at:
            print(f"  {assignment.id}: {assignment.name} - Submitted on: {assignment.submitted_at}")
        else:
            print(f"  {assignment.id}: {assignment.name} - Submission date not available.")

print("\nPending Assignments (Not Past Due):")
for course_name, assignments in pending_assignments.items():
    print(f"\nCourse: {course_name}")
    for assignment in assignments:
        # Check if the assignment has a due date
        if hasattr(assignment, 'due_at') and assignment.due_at:
            print(f"  {assignment.id}: {assignment.name} - Due: {assignment.due_at}")
            print(f"     attributes: {dir(assignment)}")
        else:
            print(f"  {assignment.id}: {assignment.name} - Due date not available.")

print("\nAssignments with No Due Date:")
for course_name, assignments in no_due_date_assignments.items():
    print(f"\nCourse: {course_name}")
    for assignment in assignments:
        print(f"  {assignment.id}: {assignment.name} - No due date.")


print("\nPending Assignments (Not Past Due) JSON:")

#asg_list = [x for (_,x) in pending_assignments.items() if hasattr(x, 'due_at') and \
#        datetime.strptime(x.due_at, "%Y-%m-%dT%H:%M:%SZ") > now]

asg_list = []
for _,x in pending_assignments.items():
    for y in x:
        asg_list.append(y)
#print(f"type: {type(asg_list[0])}")
#print(f" dir: {dir(asg_list[0])}")
#asg_list = [x._json for _,x in pending_assignments.items()]
#print(f"asg_list is {asg_list._json}\n")
#print(json.dumps({"assignments": asg_list}))

# still want to remove or overwrite one key that looks kinda secretish
json_output = json.dumps(
    [{k: v for k, v in vars(a).items() if not k.startswith('_')} for a in asg_list],
    indent=2,
    default=str
)

print(f"{json_output}")
