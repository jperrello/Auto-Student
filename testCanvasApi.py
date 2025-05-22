#!/bin/env python3

import json
import os
from canvasapi import Canvas
API_URL="https://canvas.ucsc.edu/"
API_KEY=""

canvas = Canvas(API_URL, API_KEY)

classlist = canvas.get_courses()

course_names = [course.name for course in classlist if hasattr(course, "name")]
print(json.dumps({"courses": course_names}))
